# BLUF: check_git_state 가드가 폐기형 git 명령을 링크 워크트리+dirty에서만 막고 메인·클린·안전형은 통과시키는지 무LLM으로 검증하는 회귀(#118).
"""git 상태-파괴 가드 회귀(#118).

가드의 계약은 "세 조건 모두 참일 때만 막는다"다 — (1) 폐기형 명령,
(2) 링크된 워크트리, (3) dirty. 하나라도 빠지면 통과다. 이 파일이 그 계약과
denylist 경계(무엇이 폐기형이고 무엇이 아닌가)를 고정한다.

무DB·무LLM. 실 git repo·워크트리로 조건 2·3을 실측한다(가짜 패치 아님).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import ai_harness.check_git_state as cgs

# 배선 시험이 부를 실행 파일 자리 — 전역 설치본 대신 이 체크아웃을 본다.
_LOCAL_PATH = f"{Path(sys.executable).parent}:/usr/bin:/bin"


# --- denylist 경계: 무엇이 폐기형인가 -----------------------------------------

@pytest.mark.parametrize("subcmd,args", [
    ("reset", ["--hard"]),
    ("reset", ["--hard", "HEAD~1"]),
    ("stash", []),
    ("stash", ["push", "-m", "wip"]),
    ("stash", ["-u"]),
    ("clean", ["-fd"]),
    ("clean", ["--force"]),
    ("clean", ["-xdf"]),
    ("restore", ["src/a.py"]),
    ("restore", ["."]),
    ("checkout", ["-f"]),
    ("checkout", ["-qf", "main"]),     # 번들 단문 플래그 — f 결합(MAJOR 회귀)
    ("checkout", ["--", "src/a.py"]),
    ("checkout", ["."]),
    ("switch", ["--discard-changes", "main"]),
    ("switch", ["-f", "main"]),
    ("switch", ["-qf", "main"]),        # 번들 단문 플래그(MAJOR 회귀)
])
def test_discard_forms_are_flagged(subcmd, args):
    assert cgs.discard_reason(subcmd, args) is not None, f"{subcmd} {args} 폐기형 미인식"


@pytest.mark.parametrize("subcmd,args", [
    ("reset", []),                       # mixed — 미커밋 남긴다
    ("reset", ["--soft", "HEAD~1"]),     # HEAD만 이동
    ("reset", ["src/a.py"]),             # 언스테이지
    ("stash", ["pop"]),
    ("stash", ["apply"]),
    ("stash", ["list"]),
    ("stash", ["drop"]),
    ("clean", ["-n"]),                   # dry-run — 아무것도 안 지운다
    ("clean", ["--dry-run"]),
    ("clean", ["-fn"]),                  # force+dry-run — git이 안 지운다(MAJOR 회귀)
    ("clean", ["-nf"]),                  # 순서 무관
    ("clean", ["--dry-run", "-f"]),      # 롱 dry-run이 force를 무력화
    ("restore", ["--staged", "src/a.py"]),   # 언스테이지만(워크트리 무변)
    ("checkout", ["main"]),              # 브랜치 전환 — 변경 이월/거부
    ("checkout", ["-b", "feature"]),     # 새 브랜치 생성
    ("switch", ["main"]),               # 브랜치 전환
    ("commit", ["-m", "x"]),
    ("add", ["-A"]),
    ("status", ["--porcelain"]),
])
def test_safe_forms_are_not_flagged(subcmd, args):
    assert cgs.discard_reason(subcmd, args) is None, f"{subcmd} {args} 오탐(안전형인데 막음)"


def test_restore_worktree_flag_overrides_staged_exemption():
    """--staged라도 --worktree가 함께면 워크트리를 건드리므로 폐기형이다."""
    assert cgs.discard_reason("restore", ["--staged", "--worktree", "a.py"]) is not None


# --- git 호출 파싱: 환경대입·전역플래그·-C -------------------------------------

def test_git_invocation_skips_env_assignment():
    inv = cgs.git_invocation(["FOO=bar", "git", "reset", "--hard"])
    assert inv is not None and inv[0] == "reset" and inv[1] == ["--hard"]


def test_git_invocation_captures_dash_C_and_skips_global_flags():
    inv = cgs.git_invocation(["git", "-C", "/wt", "-c", "k=v", "reset", "--hard"])
    assert inv is not None
    subcmd, args, c_dir = inv
    assert subcmd == "reset" and args == ["--hard"] and c_dir == "/wt"


def test_git_invocation_none_for_non_git():
    assert cgs.git_invocation(["ls", "-la"]) is None
    assert cgs.git_invocation(["python", "reset"]) is None


def test_split_segments_breaks_on_operators():
    segs = cgs.split_segments(["cd", "x", "&&", "git", "reset", "--hard"])
    assert segs == [["cd", "x"], ["git", "reset", "--hard"]]


# --- 조건 2·3: 실 git repo + 링크 워크트리 -------------------------------------

def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "f.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path):
    """메인 체크아웃 + 링크 워크트리 한 쌍을 만든다. 워크트리는 dirty로 둔다."""
    main = tmp_path / "main"
    main.mkdir()
    _init_repo(main)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt)],
                   cwd=main, check=True, capture_output=True)
    (wt / "f.txt").write_text("dirty edit\n", encoding="utf-8")  # 미커밋 변경
    return main, wt


def test_blocks_reset_hard_in_dirty_linked_worktree(repo_with_worktree):
    _main, wt = repo_with_worktree
    blocked = cgs.find_block("git reset --hard", str(wt))
    assert blocked is not None
    assert "reset --hard" in blocked[0]


def test_not_blocked_in_main_checkout_even_when_dirty(tmp_path):
    """메인 체크아웃은 링크 워크트리가 아니라 대상이 아니다 — 감독의 정상 git."""
    main = tmp_path / "main"
    main.mkdir()
    _init_repo(main)
    (main / "f.txt").write_text("dirty in main\n", encoding="utf-8")
    assert cgs.find_block("git reset --hard", str(main)) is None


def test_not_blocked_when_worktree_clean(repo_with_worktree):
    """깨끗하면 지울 미커밋이 없으므로 막지 않는다(조건3)."""
    main, wt = repo_with_worktree
    subprocess.run(["git", "checkout", "-q", "--", "f.txt"], cwd=wt, check=True,
                   capture_output=True)  # 클린으로 되돌림
    assert cgs.find_block("git reset --hard", str(wt)) is None


def test_cd_prefix_switches_effective_cwd(repo_with_worktree):
    """`cd <wt> && git reset --hard`는 유효 cwd가 wt로 바뀌어 막힌다."""
    main, wt = repo_with_worktree
    blocked = cgs.find_block(f"cd {wt} && git reset --hard", str(main))
    assert blocked is not None


def test_dash_C_switches_effective_cwd(repo_with_worktree):
    """`git -C <wt> reset --hard`도 그 워크트리를 대상으로 판정한다."""
    main, wt = repo_with_worktree
    blocked = cgs.find_block(f"git -C {wt} reset --hard", str(main))
    assert blocked is not None


def test_safe_git_op_in_dirty_worktree_passes(repo_with_worktree):
    """폐기형이 아니면(commit·add·status) dirty 링크 워크트리라도 통과."""
    _main, wt = repo_with_worktree
    assert cgs.find_block("git add -A", str(wt)) is None
    assert cgs.find_block("git status", str(wt)) is None
    assert cgs.find_block("git stash pop", str(wt)) is None


# --- 훅 모드: exit 코드·우회 스위치 --------------------------------------------

def _run_hook(monkeypatch, command, cwd):
    payload = json.dumps({"tool_input": {"command": command}, "cwd": cwd})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return cgs.run_hook()


def test_hook_blocks_with_exit_2(monkeypatch, repo_with_worktree):
    _main, wt = repo_with_worktree
    monkeypatch.delenv("AI_HARNESS_GIT_STATE_GUARD", raising=False)
    assert _run_hook(monkeypatch, "git reset --hard", str(wt)) == 2


def test_hook_passes_non_git(monkeypatch, repo_with_worktree):
    _main, wt = repo_with_worktree
    monkeypatch.delenv("AI_HARNESS_GIT_STATE_GUARD", raising=False)
    assert _run_hook(monkeypatch, "ls -la", str(wt)) == 0


def test_env_disable_bypasses_guard(monkeypatch, repo_with_worktree):
    """AI_HARNESS_GIT_STATE_GUARD=0이면 막히던 명령도 통과(감독 밸브)."""
    _main, wt = repo_with_worktree
    monkeypatch.setenv("AI_HARNESS_GIT_STATE_GUARD", "0")
    assert _run_hook(monkeypatch, "git reset --hard", str(wt)) == 0


def test_hook_malformed_payload_is_non_blocking(monkeypatch):
    """payload 파싱 실패는 논블로킹(fail-open) — 가드 고장이 bash를 막지 않는다."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json{"))
    assert cgs.run_hook() == 1


# --- 토크나이저: 공백 없는 셸 연산자도 세그먼트가 갈려야 한다 ------------------

@pytest.mark.parametrize("command", [
    "git reset --hard; git clean -fd",   # 세미콜론 앞 공백 없음(셸 관용구 표준형)
    "git reset --hard;echo done",        # 양쪽 공백 없음
    "git stash;echo x",
    "git reset --hard&&echo x",          # && 공백 없음
    "git reset --hard| tee log",         # 파이프
])
def test_no_space_operator_still_segments_and_blocks(repo_with_worktree, command):
    """`shlex.split`은 `--hard;`를 한 토큰으로 묶어 가드를 뚫었다(실측 회귀) —
    tokenize()가 공백 무관하게 연산자를 떼어 폐기형 첫 세그먼트를 잡아야 한다."""
    _main, wt = repo_with_worktree
    blocked = cgs.find_block(f"cd {wt} && {command}", str(wt))
    assert blocked is not None, f"{command!r} — 공백 없는 연산자로 가드가 뚫렸다"


def test_quoted_operator_is_not_split():
    """따옴표 안 세미콜론은 세그먼트를 가르지 않는다(커밋 메시지 등 오탐 방지)."""
    argv = cgs.tokenize('git commit -m "fix: a; b"')
    assert argv == ["git", "commit", "-m", "fix: a; b"]


def test_tokenize_unclosed_quote_raises_for_fail_open():
    """미닫힌 따옴표는 ValueError — find_block이 fail-open으로 통과시킨다."""
    with pytest.raises(ValueError):
        cgs.tokenize('git reset --hard "unclosed')
    assert cgs.find_block('git reset --hard "unclosed', "/tmp") is None


# --- 우회밸브: 무력화 시 통과하되 '막혔을 명령'에만 흔적을 남긴다 --------------

def test_env_disable_passes_would_block_but_leaves_trace(monkeypatch, capsys, repo_with_worktree):
    """AI_HARNESS_GIT_STATE_GUARD=0이면 통과(exit 0)시키되, 막혔을 명령엔 stderr 흔적을
    남긴다 — 밸브를 열어두고 잊어도 무엇이 통과했는지 흔적이 남는다(관측성)."""
    _main, wt = repo_with_worktree
    monkeypatch.setenv("AI_HARNESS_GIT_STATE_GUARD", "0")
    assert _run_hook(monkeypatch, "git reset --hard", str(wt)) == 0
    err = capsys.readouterr().err
    assert "AI_HARNESS_GIT_STATE_GUARD=0" in err and "reset --hard" in err


def test_env_disable_is_silent_for_non_blocking_commands(monkeypatch, capsys, repo_with_worktree):
    """무력화 상태라도 애초에 안 막힐 명령엔 무출력 — 매 bash 호출 스팸 방지."""
    _main, wt = repo_with_worktree
    monkeypatch.setenv("AI_HARNESS_GIT_STATE_GUARD", "0")
    assert _run_hook(monkeypatch, "git status", str(wt)) == 0
    assert capsys.readouterr().err == ""


# --- 배선(settings.json 쉘 한 줄) 회귀 — ADR 0029 필수조건 제3항 ---------------
#
# 유닛테스트가 아니라 **커밋되는 배선 그 자체**를 sh로 돌린다 — 실제로 무는 층은
# .claude/settings.json의 쉘 한 줄이고, 검사기 부재를 잘못 처리하면(예:
# `test -f X && cmd || exit 0`) 모든 리젝이 통과로 뒤집힌다. check_pr_body의
# 같은 회귀(test_wired_hook_*)와 동형. ADR 0029 필수조건 제3항이 이 층을 요구한다.

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _hook_command() -> str:
    """커밋된 .claude/settings.json에서 check_git_state PreToolUse 명령을 꺼낸다."""
    settings = json.loads((_REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        h["command"]
        for m in settings["hooks"]["PreToolUse"] if m.get("matcher") == "Bash"
        for h in m["hooks"] if "check-git-state" in h.get("command", "")
    ]
    assert len(commands) == 1, f"Bash용 check-git-state 훅이 1개가 아님: {commands}"
    return commands[0]


def _run_wired_hook(command: str, project_dir: Path, path: str | None = None) -> int:
    """커밋된 훅 래퍼를 실제 sh로 실행하고 종료코드를 돌려준다.

    PATH에 이 체크아웃의 실행 파일 자리를 먼저 둔다 — 배선이 부르는 것은 설치본
    `ai-harness`이고, 전역 설치본은 이 브랜치보다 낡을 수 있어 옛 코드를 재게 된다."""
    return subprocess.run(
        ["sh", "-c", _hook_command()],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True,
        env={"PATH": path if path is not None else _LOCAL_PATH,
             "CLAUDE_PROJECT_DIR": str(project_dir)},
    ).returncode


def test_wired_hook_blocks_discard_in_linked_worktree(repo_with_worktree):
    """배선된 쉘 한 줄이 링크워크트리+dirty 폐기형을 실제로 exit 2로 막는다."""
    _main, wt = repo_with_worktree
    assert _run_wired_hook(f"cd {wt} && git reset --hard", _REPO_ROOT) == 2


def test_wired_hook_allows_unrelated_command():
    """배선이 폐기형 아닌 명령은 통과시킨다(exit 0)."""
    assert _run_wired_hook("git status", _REPO_ROOT) == 0


def test_wired_hook_does_not_lock_repo_when_checker_absent(repo_with_worktree):
    """검사기가 설치돼 있지 않으면 게이트는 꺼지되 저장소를 잠그지 않는다.

    부재 시 래퍼가 비영으로 죽으면 모든 Bash 호출이 막힌다(게이트 자기잠금).
    이 배선은 설치본을 부르므로 부재 조건은 PATH에 실행 파일이 없는 상태다."""
    _main, wt = repo_with_worktree
    assert _run_wired_hook(f"cd {wt} && git reset --hard", _REPO_ROOT,
                           path="/usr/bin:/bin") == 0


def test_wired_hook_does_not_swallow_rejection(repo_with_worktree):
    """래퍼가 리젝(exit 2)을 통과로 바꾸지 않는다 — `if...then...fi`의 마지막
    명령(python) 종료코드가 그대로 전파돼야 한다."""
    _main, wt = repo_with_worktree
    assert _run_wired_hook(f"cd {wt} && git reset --hard", _REPO_ROOT) != 0
