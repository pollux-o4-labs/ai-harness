# BLUF: gen_readmes의 --staged 스코프(스테이징된 경로의 조상 폴더만 검사)를 검증하는 회귀.
"""gen_readmes --staged 스코프 회귀.

전체 스캔은 병렬 레인이 건드린 무관한 폴더의 어긋남까지 이번 커밋을 막는다.
`staged_folders()`는 이번 커밋이 실제로 바꿀 수 있는 폴더(스테이징된 경로의
조상)로 검사 범위를 좁힌다. 진짜 git 인덱스(`git diff --cached`)를 읽으므로
각 시험은 임시 git repo를 실제로 만든다(가짜 patch가 아니다).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys

from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "gen_readmes", Path(__file__).resolve().parent.parent / "src" / "ai_harness" / "gen_readmes.py"
)
gen_readmes = importlib.util.module_from_spec(_SPEC)
sys.modules["gen_readmes"] = gen_readmes
_SPEC.loader.exec_module(gen_readmes)

START = gen_readmes.MARK_START
END = gen_readmes.MARK_END


def _block(*inner: str) -> str:
    return "\n".join(["> **BLUF:** t.", "", START, *inner, END, ""])


def _git_repo(root: Path) -> None:
    """삭제·개명 시험은 커밋 기준선이 있어야 diff가 잡히므로 신원까지 맞춘다."""
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(root), check=True)


def _add(root: Path, *rel: str) -> None:
    subprocess.run(["git", "add", *rel], cwd=str(root), check=True, capture_output=True)


def _commit(root: Path) -> None:
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(root), check=True, capture_output=True)


# --- 조상 폴더 포함 ------------------------------------------------------------


def test_staged_folders_includes_ancestors_of_added_path(tmp_path):
    """스테이징된 경로가 속한 폴더와 그 조상이 대상에 들어온다."""
    _git_repo(tmp_path)
    nested = tmp_path / "sub" / "nested"
    nested.mkdir(parents=True)
    (nested / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    _add(tmp_path, "sub/nested/a.md")

    dirs = gen_readmes.staged_folders(tmp_path)
    assert set(dirs) == {tmp_path, tmp_path / "sub", nested}


def test_staged_folders_includes_folder_of_deleted_path(tmp_path):
    """삭제도 관련 폴더의 문서 목록을 바꾸므로 대상에 들어와야 한다."""
    _git_repo(tmp_path)
    old_dir = tmp_path / "old_dir"
    old_dir.mkdir()
    (old_dir / "c.md").write_text("> **BLUF:** 문서 C.\n", encoding="utf-8")
    _add(tmp_path, "-A")
    _commit(tmp_path)

    (old_dir / "c.md").unlink()
    _add(tmp_path, "-A")

    dirs = gen_readmes.staged_folders(tmp_path)
    assert old_dir in dirs


def test_staged_folders_excludes_deleted_folder_itself_but_keeps_parent(tmp_path):
    """폴더 자신이 사라지면 그 폴더는 빠지되, 부모는 남아 인덱스를 갱신해야 한다."""
    _git_repo(tmp_path)
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    (doomed / "e.md").write_text("> **BLUF:** 문서 E.\n", encoding="utf-8")
    _add(tmp_path, "-A")
    _commit(tmp_path)

    (doomed / "e.md").unlink()
    doomed.rmdir()
    _add(tmp_path, "-A")

    dirs = gen_readmes.staged_folders(tmp_path)
    assert doomed not in dirs, "사라진 폴더 자신이 대상에 남았다"
    assert tmp_path in dirs, "그 부모(루트)가 빠졌다 — 사라진 항목을 못 지운다"


def test_staged_folders_includes_both_sides_of_rename(tmp_path):
    """개명은 옛 폴더·새 폴더 양쪽 인덱스가 바뀌므로 둘 다 대상에 들어와야 한다."""
    _git_repo(tmp_path)
    src_dir = tmp_path / "src_dir"
    src_dir.mkdir()
    doc = src_dir / "d.md"
    # 개명 인식 임계(유사도)를 넘기도록 원문을 충분히 길게 둔다.
    doc.write_text("> **BLUF:** 문서 D.\n" + ("본문 " * 100) + "\n", encoding="utf-8")
    _add(tmp_path, "-A")
    _commit(tmp_path)

    dst_dir = tmp_path / "dst_dir"
    dst_dir.mkdir()
    doc.rename(dst_dir / "d.md")
    _add(tmp_path, "-A")

    dirs = gen_readmes.staged_folders(tmp_path)
    assert src_dir in dirs, "개명 옛 폴더가 빠졌다"
    assert dst_dir in dirs, "개명 새 폴더가 빠졌다"


def test_staged_folders_handles_filename_with_tab(tmp_path):
    """탭이 든 파일명은 `--name-status`(탭 구분)로는 안전하게 못 가른다.

    git은 `core.quotepath` 설정과 무관하게 이런 이름을 C 방식으로 quote한다
    (예: `"docs/a\\tb.md"`). quote를 안 풀고 그 문자열을 그대로 경로로 쓰면
    존재하지 않는 경로가 되어, 실제로 영향받은 `docs/`가 조상 집합에서
    조용히 빠진다 — `-z`(NUL 구분자)는 이런 이름도 quote 없이 그대로 내보내
    이 문제를 근본에서 제거한다."""
    _git_repo(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    weird = docs / "a\tb.md"
    weird.write_text("> **BLUF:** 문서.\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", str(weird)], cwd=str(tmp_path),
                    check=True, capture_output=True)

    dirs = gen_readmes.staged_folders(tmp_path)
    assert docs in dirs, "탭이 든 파일명 때문에 실제 영향받은 폴더가 스코프에서 빠졌다"


def _fake_diff_run(monkeypatch, stdout: str) -> None:
    """`git diff --cached ...`만 흉내내고 나머지 호출(예: is_git_ignored의
    check-ignore)은 진짜 subprocess.run으로 흘려보낸다 — 안 그러면 이 스텁이
    모든 호출을 가로채 무관한 판정까지 rc 0으로 오염시킨다."""
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_staged_folders_tolerates_truncated_status_token(tmp_path, monkeypatch):
    """상태 토큰 뒤에 경로 토큰이 안 오고 스트림이 끊겨도 죽지 않고 멈춘다.

    실제 git -z 출력은 이렇게 끊기지 않는다 — 방어 분기(파싱 실패로 통째로
    죽는 대신 그 지점에서 멈춤)의 계약을 확인하려고 직접 흉내낸다. 끊기기
    전까지 읽은 정상 항목(`changed/a.md`)은 그대로 반영돼야 한다."""
    changed = tmp_path / "changed"
    changed.mkdir()
    # 정상 항목 하나(M\0changed/a.md\0) 뒤에 경로 없는 상태 토큰만 남겨 끊는다.
    _fake_diff_run(monkeypatch, "M\0changed/a.md\0M\0")
    assert gen_readmes.staged_folders(tmp_path) == [tmp_path, changed]


def test_staged_folders_tolerates_truncated_rename_token(tmp_path, monkeypatch):
    """개명 상태 토큰 뒤에 옛/새 경로 중 하나만 오고 끊겨도 죽지 않고 멈춘다."""
    _fake_diff_run(monkeypatch, "R100\0old/x.md\0")
    assert gen_readmes.staged_folders(tmp_path) == []


def test_staged_folders_does_not_drop_last_entry_without_trailing_nul(tmp_path, monkeypatch):
    """트레일링 NUL이 없어도 마지막 항목을 빈 토큰으로 오인해 지우면 안 된다.

    실제 git -z 출력은 항상 트레일링 NUL로 끝난다. 그 가정이 깨진 입력에서도
    "마지막 토큰이 빈 문자열이면 버린다"는 방어가 진짜 경로를 지우지 않는지
    확인한다."""
    changed = tmp_path / "changed"
    changed.mkdir()
    _fake_diff_run(monkeypatch, "M\0changed/a.md")  # 트레일링 \0 없음
    assert gen_readmes.staged_folders(tmp_path) == [tmp_path, changed]


# --- --check --staged 스코프: 무관한 폴더의 어긋남은 안 막는다 ------------------


def test_staged_scope_ignores_drift_outside_staged_folders(tmp_path):
    """스테이징 밖 폴더의 어긋남은 --staged에서 리젝되지 않는다."""
    _git_repo(tmp_path)

    changed = tmp_path / "changed"
    changed.mkdir()
    (changed / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "b.md").write_text("> **BLUF:** 문서 B.\n", encoding="utf-8")

    # 전체 실행 1회차는 자식 README가 아직 없어 루트 인덱스가 "README 없음"으로
    # 찍힌다 — 단일 패스라 그 시점 이후 생긴 자식 README를 못 본다. 고정점(같은
    # 트리를 다시 돌려도 안 바뀌는 상태)에 이르도록 한 번 더 돌린 뒤 기준선을
    # 커밋한다(안 그러면 기준선 자체가 재계산 시 "정당한" 어긋남을 낸다).
    assert gen_readmes.main(["--root", str(tmp_path)]) == 0
    assert gen_readmes.main(["--root", str(tmp_path)]) == 0
    _add(tmp_path, "-A")
    _commit(tmp_path)

    # stale의 자동생성 블록 안만 손으로 낡게 만든다(상단 폴더 BLUF는 그대로
    # 둔다 — 안 그러면 그 BLUF를 옮겨 싣는 루트 인덱스까지 같이 어긋나
    # "루트도 스테이징 대상이라 정당하게 어긋난 것"과 뒤섞인다). 스테이징하지 않는다.
    stale_before = (stale / "README.md").read_text(encoding="utf-8")
    stale_head = stale_before.split(START, 1)[0].rstrip()
    (stale / "README.md").write_text(
        "\n".join([stale_head, "", START, "- `old.md` — 옛 항목.", END, ""]),
        encoding="utf-8",
    )

    # changed는 새 문서를 추가하고, 그 폴더 자신의 README도 같이 맞춰 스테이징한다
    # — 이 폴더는 대상 안이지만 어긋남이 없어야 "밖" 폴더만 검증하는 시험이 된다.
    (changed / "c.md").write_text("> **BLUF:** 문서 C.\n", encoding="utf-8")
    changed_index = gen_readmes.build_index_block(changed, [])
    (changed / "README.md").write_text(
        gen_readmes.compose_readme(changed, changed_index), encoding="utf-8"
    )
    _add(tmp_path, "changed/c.md", "changed/README.md")

    rc = gen_readmes.main(["--root", str(tmp_path), "--check", "--staged"])
    assert rc == 0, "스테이징 밖 폴더의 어긋남이 --staged를 막았다"


def test_staged_scope_still_rejects_drift_inside_staged_folder(tmp_path):
    """좁히더라도 스테이징된 폴더 자신의 어긋남은 여전히 잡아야 한다(맹목적 통과 방지)."""
    _git_repo(tmp_path)
    changed = tmp_path / "changed"
    changed.mkdir()
    (changed / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    (changed / "README.md").write_text(_block("### 문서", "- `old.md` — 옛 항목."),
                                        encoding="utf-8")
    _add(tmp_path, "changed/a.md")

    rc = gen_readmes.main(["--root", str(tmp_path), "--check", "--staged"])
    assert rc == gen_readmes.DRIFT
