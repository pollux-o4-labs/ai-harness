# BLUF: gen_readmes의 자동생성 블록 파괴 방지와 gitignore 폴더 제외를 검증하는 회귀.
"""gen_readmes의 자동생성 블록 파괴 방지 회귀.

폴더 README 상단의 자동생성 목차 블록(BLUF-INDEX — 각 문서의 첫 줄 요약을 모아
놓은 색인)은 재생성 때 통째로 교체된다. 그 안에 사람이 손으로 쓴 줄은 말없이
사라지고, 사라지면 어긋남(drift)도 같이 없어져 커밋 게이트가 울릴 근거조차 남지
않는다. 그래서 파괴 전에 멈춰야 하고, 이 파일이 그 성질을 고정한다.

DB도 LLM(언어모델)도 안 쓴다 — 순수 파일 조작이라 어디서 돌려도 같은 결과다.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_generated_entries_are_not_flagged_as_handwritten():
    """생성 형식(`- \\`이름\\` — 설명`·`### 제목`)은 손글씨가 아니다."""
    content = _block("### 문서", "- `a.md` — 설명.", "- `sub/` — 폴더 설명.", "")
    assert gen_readmes.handwritten_in_block(content) == []


def test_handwritten_line_in_block_is_detected():
    content = _block("### 문서", "- `a.md` — 설명.", "- 손으로 쓴 메모.")
    assert gen_readmes.handwritten_in_block(content) == ["- 손으로 쓴 메모."]


def test_prose_in_block_is_detected():
    """불릿이 아닌 산문도 생성물이 아니다."""
    content = _block("### 문서", "이 폴더는 중요합니다.")
    assert gen_readmes.handwritten_in_block(content) == ["이 폴더는 중요합니다."]


def test_text_outside_block_is_not_flagged():
    """블록 밖은 재생성이 보존하므로 파괴 대상이 아니다 — 여기서 잡으면 오탐."""
    content = _block("### 문서", "- `a.md` — 설명.") + "\n블록 밖 메모.\n"
    assert gen_readmes.handwritten_in_block(content) == []


def test_missing_markers_yields_nothing():
    """마커 없는 README는 블록이 없으니 파괴될 것도 없다."""
    assert gen_readmes.handwritten_in_block("> **BLUF:** t.\n\n아무 글.\n") == []


def test_run_aborts_without_writing_when_block_hand_edited(tmp_path, monkeypatch, capsys):
    """**파괴 전에 멈춘다** — 쓰고 나서 알리면 이미 지워진 뒤라 알림이 소용없다."""
    doc = tmp_path / "a.md"
    doc.write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(_block("### 문서", "- `a.md` — 문서 A.", "- 손으로 쓴 메모."),
                      encoding="utf-8")
    before = readme.read_text(encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    assert rc == gen_readmes.HANDWRITTEN_ABORT
    assert readme.read_text(encoding="utf-8") == before, "멈춘다고 해놓고 썼다"
    err = capsys.readouterr().err
    assert "손으로 쓴 메모" in err, "무엇이 사라질지 안 알렸다"
    # 목적지를 줘야 한다 — "지워라"만 하면 작업자가 어디로 옮길지 모르고,
    # 모르면 블록 안에서 형식만 고치다 헛수고한다(축약은 목적지가 정의한다).
    assert "BLUF" in err, "어디로 옮길지 안 알렸다"


def test_abort_and_drift_use_distinct_exit_codes():
    """호출자가 처방을 덧붙일지 정하려면 '왜 실패했나'가 종료코드로 와야 한다."""
    assert gen_readmes.HANDWRITTEN_ABORT != gen_readmes.DRIFT
    assert gen_readmes.HANDWRITTEN_ABORT != 0 and gen_readmes.DRIFT != 0


def test_check_reports_drift_code_when_no_handwriting(tmp_path, monkeypatch):
    """손글씨 없이 인덱스만 어긋나면 DRIFT — 재생성으로 풀리는 경우다."""
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(_block("### 문서", "- `stale.md` — 옛 항목."),
                                        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path), "--check"])
    assert gen_readmes.main() == gen_readmes.DRIFT


def test_abort_is_all_or_nothing_across_folders(tmp_path, monkeypatch):
    """한 폴더가 걸리면 **다른 폴더도 안 쓴다** — 반쪽 실행이 제일 나쁘다."""
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "b.md").write_text("> **BLUF:** 문서 B.\n", encoding="utf-8")
    (clean / "README.md").write_text(_block("### 문서", "- `stale.md` — 옛 항목."),
                                     encoding="utf-8")
    clean_before = (clean / "README.md").read_text(encoding="utf-8")

    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(_block("### 문서", "- 손글씨."), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    assert gen_readmes.main() == gen_readmes.HANDWRITTEN_ABORT
    assert (clean / "README.md").read_text(encoding="utf-8") == clean_before


# --- gitignore된 폴더는 관리 대상이 아니다 ------------------------------------
#
# 실사고(pollux-o4-labs/vector-graph-ontology#21 증상 2 — 그 레포엔 `snapshots/`라는
# gitignore된 스크래치 폴더가 있었다. 이 레포엔 없으니 여기서 찾지 마라):
# gen_readmes가 gitignore된 `snapshots/` 안 README를 관리 대상으로 삼아
# drift를 냈고, 그 README는 추적되지 않아 커밋할 수 없으니 --check가 영원히
# 비영 → pre-commit이 무관한 커밋까지 통째로 막았다. 추적 안 되는 폴더는 빼야 한다.


def _git_repo(root: Path) -> None:
    """check-ignore 배선까지 실제로 태우려면 진짜 git repo여야 한다(가짜 패치 아님)."""
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True, capture_output=True)


def test_iter_folders_skips_gitignored(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "kept").mkdir()

    names = {f.name for f in gen_readmes.iter_folders(tmp_path)}
    assert "kept" in names, "추적되는 폴더를 빠뜨렸다"
    assert "scratch" not in names, "gitignore된 폴더까지 내려간다 — 커밋 봉쇄의 원인"


def test_gitignored_folder_not_generated_or_indexed(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    scratch = tmp_path / "scratch"
    (scratch / "upload").mkdir(parents=True)

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    assert gen_readmes.main() == 0

    assert not (scratch / "README.md").exists(), "gitignore된 폴더에 README를 자가 생성"
    assert not (scratch / "upload" / "README.md").exists(), "gitignore 하위까지 생성"
    root_readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "scratch/" not in root_readme, "gitignore된 폴더가 상위 인덱스에 실림 — 즉시 drift"


# --- 기본 루트는 대상 저장소다 -------------------------------------------------
#
# gen_readmes.py가 scripts/에서 src/ai_harness/로 이사하며 REPO_ROOT(=__file__의
# parent.parent)가 repo 루트에서 번들 패키지 src/로 밀렸다. 그걸 --root 기본값으로
# 두면 설치형 CLI로 남의 repo에서 돌 때 대상이 아니라 설치된 패키지 폴더를 훑는다
# (사실상 고장). 기본 루트는 대상 저장소 git 루트여야 한다 — check-pr·check-doc과 동일.


def test_default_root_is_target_repo_not_bundled(tmp_path, monkeypatch):
    """--root 없으면 대상 저장소(git 루트)를 훑는다 — 번들 패키지 src/가 아니라."""
    _git_repo(tmp_path)
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # cwd 기준 git toplevel = tmp_path
    monkeypatch.setattr(sys, "argv", ["gen_readmes.py"])  # --root 생략

    assert gen_readmes.main() == 0
    readme = tmp_path / "README.md"
    assert readme.exists(), "대상 repo 루트에 README를 안 만들었다 — 엉뚱한 루트"
    assert "a.md" in readme.read_text(encoding="utf-8"), "대상 repo를 루트로 훑지 않았다"
