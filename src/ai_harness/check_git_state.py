#!/usr/bin/env python3
# BLUF: 링크된(2차) 워크트리에서 미커밋 변경을 지우는 git 명령(reset --hard·stash·clean -f·checkout/restore/switch 폐기형)을 실행 전에 막는 Claude Code PreToolUse 가드(stdlib only, LLM 0) — 병렬 슬라이스가 서로의 미커밋을 날리는 병렬 슬라이스 사고를 구조로 차단.
"""git 상태-파괴 가드 — 병렬 워크트리 미커밋 보호.

병렬 슬라이스가 한 워크트리를 공유하면, 한 슬라이스가 부른 `git reset --hard`·
`git stash`·`git clean -f`·`git checkout -- <경로>`가 **자기 파일만이 아니라
워크트리 전체**의 미커밋 변경을 지운다 — 다른 슬라이스가 손대던 미커밋이 통째로
증발한다(형제 저장소에서 실사고 2회). git 조작은 파일 단위가 아니라 워크트리 단위라, 규칙
06/10의 파일-경계 분리로는 안 막힌다(그 조문들은 편집 충돌만 다루고 git 상태 층은
비어 있다).

git엔 checkout/reset/stash/clean을 가로채는 pre-* 훅이 없다(post-checkout은
사후라 이미 지워진 뒤다). 대신 Claude Code의 **PreToolUse(Bash) 훅**으로 명령
문자열을 실행 전에 보고, 아래 셋이 **모두** 참일 때만 막는다(exit 2):

  1. 명령이 미커밋 변경을 폐기하는 형태다(_discard_reason의 denylist).
  2. 그 명령이 도는 곳이 **링크된 워크트리**다(git-dir != git-common-dir).
     메인 체크아웃(감독이 보통 쓰는 곳)은 대상이 아니다 — 병렬-슬라이스
     시나리오가 링크 워크트리에 국한되고, 메인까지 막으면 감독의 정상
     git(reset·stash를 일상적으로 쓴다)을 오탐 차단해 사람이 게이트를 꺼버린다.
  3. 그 워크트리에 지울 미커밋 변경이 실제로 있다(`git status --porcelain` 비어있지
     않음). 깨끗하면 무엇도 안 지우므로 막지 않는다 — 이 조건이 harm(미커밋
     증발) 자체를 인코딩한다.

**우회(런타임 무력화)**: `AI_HARNESS_GIT_STATE_GUARD=0`이면 통과시킨다 — 감독이 실제로
폐기가 필요할 때 여는 밸브다. 통과시키되 **막혔을 명령엔 stderr 흔적을 남긴다**
(밸브를 열어두고 잊으면 이후 파괴가 무흔적 통과하는 관측성 구멍을 막는다 —
우회 시 가시 출력을 남기는 선례와 동형). 구조적 차단 +
런타임 무력화 = 직교 두 층. 구현자는 폐기가 필요하면 감독에게 요청한다 — git 상태 조작은 구현자 소관 밖이다.

**정직 표기 — 한계**:
  - denylist는 완결 목록이 아니라 관측된 폐기형이다. 서브셸·별칭·비표준 형태는
    안 잡힐 수 있다 — 그때는 조건3(dirty)·커밋 산출물 기준 검증이 백스톱이다.
  - 링크-워크트리 밖(공유 루트 병렬)은 안 잡는다 — 그쪽은 슬라이스마다 즉시
    커밋으로 봉인하는 방식과 커밋 산출물 기준 검증에
    맡긴다. 메인을 막지 않는 대가로 택한 경계다.
  - 가드 자체가 못 판단하면(파싱 실패·git 없음·git 오류) **fail-open**으로
    통과시킨다 — 좁은 보호막 하나가 고장 났다고 bash 전체를 막으면 피해가 더 크다
    (check_pr_body의 payload 파싱 실패 논블로킹과 같은 결).

**설치**: `.claude/settings.json`의 PreToolUse(Bash) 훅에 배선한다(check_pr_body와
같은 방식 — 별도 install 단계 없이 체크인된 설정이 곧 설치다).

**모드**:
  python scripts/check_git_state.py --hook          # PreToolUse(stdin=훅 JSON, exit 2=차단)
  python scripts/check_git_state.py --check "<cmd>"  # CLI dry-run(막을 명령이면 exit 2, 사유 출력)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ai_harness.shell_scan import split_segments, tokenize

# 런타임 무력화 스위치(감독 밸브). "=0"만 무력화로 본다 — 미설정=켜짐(기본 보호).
_ENV_DISABLE = "AI_HARNESS_GIT_STATE_GUARD"

# 셸 문장 경계 — 명령을 세그먼트로 나눠 각 세그먼트에서 git 호출을 찾는다.
# `VAR=val git ...`의 선행 환경 대입(등호 앞이 순수 식별자).
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# git 전역 플래그 중 **값을 소비**하는 것 — subcommand를 찾을 때 값 토큰을 건너뛴다.
# 완결 목록이 아니라 관측되는 대로 늘리는 상습범 목록(규칙 09).
_GIT_GLOBAL_VALUE_FLAGS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)

# stash의 **안전한** 하위명령 — 워크트리 미커밋을 폐기하지 않는다. 이 목록에
# 없으면(바로 `git stash`, 또는 push/save/-u 등) push로 보고 폐기형 처리한다.
_STASH_SAFE = frozenset(
    {"pop", "apply", "list", "show", "drop", "clear", "branch", "create", "store"}
)


def git_invocation(seg: list[str]) -> tuple[str, list[str], str | None] | None:
    """세그먼트가 git 호출이면 (subcommand, subcommand 뒤 인자들, -C 디렉터리)를
    반환한다. 아니면 None.

    선행 `VAR=val` 환경 대입을 건너뛰고, `git -C dir -c k=v <subcmd>`의 전역
    플래그(값 소비형은 값 토큰까지)를 건너뛴다. `-C`의 값은 유효 cwd 판정에
    쓰려고 함께 반환한다(여러 번이면 마지막이 이긴다 — git과 동일)."""
    i = 0
    while i < len(seg) and _ENV_ASSIGN.match(seg[i]):
        i += 1
    if i >= len(seg) or Path(seg[i]).name != "git":
        return None
    i += 1  # 'git' 다음부터
    c_dir: str | None = None
    while i < len(seg) and seg[i].startswith("-"):
        tok = seg[i]
        if tok == "-C" and i + 1 < len(seg):
            c_dir = seg[i + 1]
            i += 2
        elif tok in _GIT_GLOBAL_VALUE_FLAGS and i + 1 < len(seg):
            i += 2
        else:
            i += 1  # 값 없는 전역 플래그(-p·--no-pager 등) 또는 --opt=val 붙은 형태
    if i >= len(seg):
        return None
    return seg[i], seg[i + 1:], c_dir


def _has_short_flag(tok: str, letter: str) -> bool:
    """토큰이 `letter`를 담은 단문 결합 플래그인가 — `-f`·`-qf`·`-xdf` 등.
    긴 플래그(`--force`)·값(`file`)은 여기서 안 잡는다(각 호출부가 따로 본다)."""
    return tok.startswith("-") and not tok.startswith("--") and letter in tok


def _has_force(args: list[str]) -> bool:
    """args에 강제(`-f`) 플래그가 있는가 — `--force` 또는 f 담은 단문 결합.
    clean·checkout·switch가 공유한다(예전엔 clean만 단문결합을 봤고 checkout/
    switch는 `"-f" in args` 정확일치라 `-qf`를 놓쳤다 — 실측 회귀)."""
    return "--force" in args or any(_has_short_flag(a, "f") for a in args)


def _is_clean_dryrun(args: list[str]) -> bool:
    """git clean이 dry-run인가 — `--dry-run` 또는 n 담은 단문 결합(`-n`·`-fn`).
    `-fn`은 force가 있어도 git이 아무것도 안 지운다(실측: `Would remove`만 출력).
    이 경우를 폐기형으로 오탐하면 무해한 명령이 막혀 사람이 가드를 꺼버린다."""
    return "--dry-run" in args or any(_has_short_flag(a, "n") for a in args)


def discard_reason(subcmd: str, args: list[str]) -> str | None:
    """폐기형 git 명령이면 사람이 읽을 사유, 아니면 None. 미커밋 변경을 실제로
    버리거나 워크트리 밖으로 치우는 형태만 denylist에 올린다(브랜치 전환·언스테이지
    같은 비파괴 형태는 유예 — 오탐이 게이트를 죽인다)."""
    if subcmd == "reset":
        # --hard만 워크트리를 되돌린다(--soft/--mixed는 미커밋을 남긴다).
        return ("git reset --hard — 워크트리의 미커밋 변경을 전부 버린다"
                if "--hard" in args else None)
    if subcmd == "stash":
        sub = next((a for a in args if not a.startswith("-")), None)
        if sub in _STASH_SAFE:
            return None  # pop/apply/list/... 는 미커밋을 폐기하지 않는다
        return ("git stash(push) — 워크트리의 모든 미커밋을 치운다(다른 슬라이스 "
                "것까지 함께 사라진다)")
    if subcmd == "clean":
        # dry-run(`-n`·`-fn`·`--dry-run`)은 아무것도 안 지우므로 force가 있어도
        # 폐기형이 아니다 — force 판정보다 먼저 걸러 오탐을 막는다.
        if _is_clean_dryrun(args):
            return None
        return ("git clean -f — 미추적 파일(다른 슬라이스의 새 파일 포함)을 지운다"
                if _has_force(args) else None)
    if subcmd == "restore":
        # 기본은 워크트리 원복(폐기). `--staged`만이면 언스테이지라 워크트리 무변.
        staged_only = "--staged" in args and "--worktree" not in args and "-W" not in args
        return (None if staged_only
                else "git restore — 워크트리의 미커밋 변경을 원복(폐기)한다")
    if subcmd == "checkout":
        # `-qf`처럼 f가 다른 단문과 결합돼도 강제 폐기다(`_has_force`가 결합 인식).
        if _has_force(args):
            return "git checkout -f — 미커밋 변경을 강제로 버리고 전환한다"
        # 경로형(`git checkout -- 경로`·`git checkout .`)은 그 경로의 미커밋을
        # 버린다. 브랜치 전환(`git checkout <브랜치>`·`-b`)은 변경을 이월하거나
        # 거부하므로 유예한다 — 브랜치인지 경로인지 못 가르는 애매한 인자는 막지
        # 않는다(오탐 최소화). `--`나 `.`이 있으면 확실한 경로형이다.
        if "--" in args or "." in args:
            return "git checkout <경로> — 그 경로의 미커밋 변경을 버린다"
        return None
    if subcmd == "switch":
        if _has_force(args) or "--discard-changes" in args:
            return "git switch --discard-changes — 미커밋 변경을 버리고 전환한다"
        return None
    return None


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess | None:
    """cwd에서 git을 돌린다. git이 없거나 OS 오류면 None(호출자가 fail-open)."""
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError:
        return None


def is_linked_worktree(cwd: str) -> bool:
    """cwd가 링크된(2차) 워크트리면 True. 메인 체크아웃·비-git이면 False.

    링크 워크트리는 git-dir(`.git/worktrees/<name>`)과 git-common-dir(`.git`)이
    다르다. common-dir은 상대경로(`.git`)로 올 수 있어 cwd 기준으로 절대화해
    비교한다(감사로 확인한 신호)."""
    gd = _git(cwd, "rev-parse", "--absolute-git-dir")
    gc = _git(cwd, "rev-parse", "--git-common-dir")
    if gd is None or gc is None or gd.returncode != 0 or gc.returncode != 0:
        return False
    git_dir = Path(gd.stdout.strip())
    common = Path(gc.stdout.strip())
    if not common.is_absolute():
        common = Path(cwd) / common
    try:
        return git_dir.resolve() != common.resolve()
    except OSError:
        return False


def is_dirty(cwd: str) -> bool:
    """cwd 워크트리에 지울 미커밋 변경(추적 변경·미추적 파일)이 있으면 True."""
    r = _git(cwd, "status", "--porcelain")
    if r is None or r.returncode != 0:
        return False
    return r.stdout.strip() != ""


def _resolve(cur: str, target: str) -> str:
    """target을 cur 기준으로 해석한 경로 문자열(절대면 그대로)."""
    p = Path(target)
    return str(p if p.is_absolute() else Path(cur) / p)


def find_block(command: str, default_cwd: str) -> tuple[str, str] | None:
    """명령을 훑어 '막아야 할' 폐기형 git 세그먼트를 찾으면 (사유, cwd)를,
    없으면 None을 반환한다. cwd는 선행 `cd`와 git `-C`를 반영한 유효 디렉터리다.

    파싱 실패는 None(fail-open) — 가드가 못 읽는 명령을 막으면 bash가 통째로
    잠긴다. 실제 차단 판정(링크 워크트리 + dirty)은 확신될 때만 한다."""
    try:
        argv = tokenize(command)
    except ValueError:
        return None
    cwd = default_cwd
    for seg in split_segments(argv):
        if not seg:
            continue
        # 선행 `cd <dir>`는 이후 세그먼트의 유효 cwd를 바꾼다(`cd wt && git reset`).
        if seg[0] == "cd" and len(seg) >= 2 and not seg[1].startswith("-"):
            cwd = _resolve(cwd, seg[1])
            continue
        inv = git_invocation(seg)
        if inv is None:
            continue
        subcmd, args, c_dir = inv
        reason = discard_reason(subcmd, args)
        if reason is None:
            continue
        repo_cwd = _resolve(cwd, c_dir) if c_dir else cwd
        if is_linked_worktree(repo_cwd) and is_dirty(repo_cwd):
            return reason, repo_cwd
    return None


def _block_message(reason: str, cwd: str) -> str:
    return (
        f"[check_git_state] 차단 — {reason}.\n"
        f"  이 명령이 도는 워크트리({cwd})는 링크된(2차) 워크트리이고 미커밋 변경이 있다.\n"
        f"  워크트리 조작은 파일 단위가 아니라 워크트리 전체라, 병렬 슬라이스의\n"
        f"  미커밋까지 함께 사라진다(실사고 2회).\n"
        f"  → 먼저 네 슬라이스를 커밋해 봉인하라. 폐기가 정말 필요하면\n"
        f"    감독에게 요청하거나, 감독이라면 `export {_ENV_DISABLE}=0` 후 다시 실행하라."
    )


def run_hook() -> int:
    """Claude Code PreToolUse 훅. stdin=훅 JSON. exit 2 = 툴 호출 차단."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[check_git_state] 훅 payload 파싱 실패 — 통과(fail-open): {e}",
              file=sys.stderr)
        return 1  # 논블로킹 — 가드 고장으로 작업을 막지 않는다
    command = (payload.get("tool_input") or {}).get("command", "") or ""
    default_cwd = payload.get("cwd") or os.getcwd()
    try:
        blocked = find_block(command, default_cwd)
    except Exception as e:  # 가드 결함이 bash 전체를 막으면 안 된다(fail-open)
        print(f"[check_git_state] 가드 내부 오류 — 통과(fail-open): {e}", file=sys.stderr)
        return 1
    if blocked is None:
        return 0
    reason, cwd = blocked
    # 우회밸브: 무력화 상태면 통과시키되 **무엇을** 통과시켰는지 흔적을 남긴다.
    # 우회 시 가시 출력을 남기는 관례와 동형 —
    # 밸브를 열어두고 잊으면 이후 파괴가 무흔적 통과하는 관측성 구멍이 생긴다.
    # 흔적은 '막혔을 명령'에만 찍는다(매 bash 호출마다 찍으면 스팸이라 무용).
    if os.environ.get(_ENV_DISABLE) == "0":
        print(f"[check_git_state] {_ENV_DISABLE}=0 — 가드 무력화, 통과 허용: "
              f"{reason} (@ {cwd})", file=sys.stderr)
        return 0
    print(_block_message(reason, cwd), file=sys.stderr)
    return 2


def run_check(command: str) -> int:
    """CLI dry-run — 막을 명령이면 사유를 출력하고 exit 2, 아니면 exit 0."""
    blocked = find_block(command, os.getcwd())
    if blocked is None:
        print("[check_git_state] 통과 — 막을 폐기형 git 명령 없음(또는 대상 워크트리 아님).")
        return 0
    reason, cwd = blocked
    if os.environ.get(_ENV_DISABLE) == "0":
        print(f"[check_git_state] {_ENV_DISABLE}=0 — 가드 무력화(통과). "
              f"무력화 아니면 막혔을 명령: {reason} (@ {cwd})")
        return 0
    print(_block_message(reason, cwd), file=sys.stderr)
    return 2


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog=prog,
        description="git 상태-파괴 가드(병렬 워크트리 미커밋 보호)",
    )
    ap.add_argument("--hook", action="store_true",
                    help="Claude Code PreToolUse 훅 모드(stdin=훅 JSON, exit 2=차단)")
    ap.add_argument("--check", metavar="CMD",
                    help="CLI dry-run — 주어진 명령이 막힐지 판정(exit 2=막힘)")
    args = ap.parse_args(argv)

    if args.hook:
        return run_hook()
    if args.check is not None:
        return run_check(args.check)
    ap.error("--hook 또는 --check 중 하나가 필요하다")


if __name__ == "__main__":
    sys.exit(main())
