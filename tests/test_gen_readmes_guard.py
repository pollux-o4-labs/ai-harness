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

import pytest
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


# --- extract_bluf: agent-def frontmatter description 대체 인덱싱 ---------------
#
# 에이전트 정의(.md)는 `> **BLUF:**` 골격을 안 쓰고 frontmatter description을 쓴다
# (docs_format/agent-def.md 폼). extract_bluf가 그 description을 BLUF 소스로 잡되,
# 본문의 우연한 `description:` 줄은 오탐하지 않아야 한다.


def test_extract_bluf_reads_frontmatter_description(tmp_path):
    """frontmatter description을 BLUF 소스로 뽑는다(agent-def 폼)."""
    f = tmp_path / "agent.md"
    f.write_text(
        "---\nname: reviewer-x\ndescription: 상설 리뷰어 — 코드 차원.\n---\n\n본문.\n",
        encoding="utf-8",
    )
    assert gen_readmes.extract_bluf(f) == "상설 리뷰어 — 코드 차원."


def test_extract_bluf_prefers_bluf_over_frontmatter_description(tmp_path):
    """BLUF 줄과 frontmatter description이 둘 다면 명시 BLUF가 이긴다."""
    f = tmp_path / "both.md"
    f.write_text(
        "---\ndescription: frontmatter 설명.\n---\n\n> **BLUF:** 본문 BLUF.\n",
        encoding="utf-8",
    )
    assert gen_readmes.extract_bluf(f) == "본문 BLUF."


def test_extract_bluf_ignores_body_description_without_frontmatter(tmp_path):
    """frontmatter가 아닌 본문의 `description:` 줄은 BLUF로 오인하지 않는다."""
    f = tmp_path / "prose.md"
    f.write_text(
        "# 제목\n\ndescription: 이건 본문 설명이지 BLUF가 아니다.\n",
        encoding="utf-8",
    )
    assert gen_readmes.extract_bluf(f) is None


# --- 마커는 줄 시작 앵커로만 매치한다(파괴 경로 1) ------------------------------
#
# 실사고(docs/history/B-autogen-marker-substring-match-hides-violations.md):
# 이 마커 문법을 설명하는 산문 문장이 본문 중간에 그대로 인용되면, 종전의 단순
# 포함(`in`) 판정이 그 지점을 블록 시작으로 오인했다. check_doc_form.py의
# `_AUTOGEN_START`/`_AUTOGEN_END`는 이미 줄 시작 앵커로 고쳐졌는데, 마커를 만들어
# 내는 이 파일(gen_readmes.py)만 그 수정을 못 받았었다.


def test_compose_readme_preserves_prose_mention_of_marker(tmp_path):
    """마커 문법을 산문 중간(줄 시작이 아님)에 인용해도 블록 경계로 오인해
    그 뒤 손글씨 문단을 지우면 안 된다 — 실제 파괴 재현."""
    START, END = gen_readmes.MARK_START, gen_readmes.MARK_END
    folder = tmp_path
    (folder / "README.md").write_text(
        "> **BLUF:** t.\n\n"
        f"이 도구가 만드는 블록은 `{START}` 로 시작한다.\n\n"
        "- 반드시 보존돼야 하는 손글씨 노트.\n\n"
        f"{START}\n"
        "### 문서\n"
        "- `stale.md` — 옛 항목.\n"
        f"{END}\n\n"
        "꼬리 문단 — 이것도 보존돼야 한다.\n",
        encoding="utf-8",
    )

    new_block = gen_readmes.build_index_block(folder, [])
    result = gen_readmes.compose_readme(folder, new_block)

    assert "반드시 보존돼야 하는 손글씨 노트" in result, (
        "산문 중간의 마커 인용을 블록 시작으로 오인해 그 뒤 손글씨를 지웠다"
    )
    assert "꼬리 문단" in result, "꼬리 보존 문단까지 사라졌다"


# --- README가 심볼릭 링크면 원본을 덮어쓰지 않는다(파괴 경로 2) -----------------


def test_symlinked_readme_is_skipped_not_overwritten(tmp_path, monkeypatch):
    """README.md가 다른 폴더의 문서를 가리키는 심볼릭 링크면, 쓰지 않고
    건너뛰어야 한다 — 안 그러면 링크가 가리키는 원본(폴더 밖 파일)이 덮어써진다."""
    shared = tmp_path / "shared"
    shared.mkdir()
    original = shared / "ORIGINAL.md"
    original_content = "다른 폴더가 공유하는 원본 문서 — gen_readmes가 손대면 안 된다.\n"
    original.write_text(original_content, encoding="utf-8")

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "sub.md").write_text("> **BLUF:** 서브 문서.\n", encoding="utf-8")
    (sub / "README.md").symlink_to(original)

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    assert rc == 0
    assert original.read_text(encoding="utf-8") == original_content, (
        "심볼릭 링크가 가리키는 폴더 밖 원본을 덮어썼다"
    )


# --- 비-UTF8 README는 손상된 채 재저장하지 않는다(파괴 경로 3) ------------------


def test_non_utf8_readme_is_skipped_not_corrupted(tmp_path, monkeypatch):
    """CP949 등 비-UTF8 README를 errors="replace"로 읽어 그대로 되쓰면 원본
    바이트가 대체문자로 영구 손상된다 — 엄격 디코드 실패 시 건너뛰어야 한다."""
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    cp949_bytes = "> **BLUF:** 한글 제목.\n\n손글씨 문단.\n".encode("cp949")
    readme.write_bytes(cp949_bytes)

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    assert rc == 0
    assert readme.read_bytes() == cp949_bytes, "비-UTF8 README를 손상시켰다"


# --- 쓰기 도중 OS 오류는 DRIFT·HANDWRITTEN_ABORT와 겹치지 않는 코드로 끝난다(파괴 경로 4) ---


def test_write_failure_code_is_distinct_from_drift_and_handwritten_abort():
    """새 종료코드가 기존 두 코드와 겹치면 pre-commit이 원인을 못 가른다."""
    assert gen_readmes.WRITE_FAILURE not in (0, gen_readmes.DRIFT, gen_readmes.HANDWRITTEN_ABORT)


def test_write_failure_mid_batch_reports_progress_and_distinct_code(tmp_path, monkeypatch, capsys):
    """쓰기 도중 한 파일에서 OS 오류가 나면, 이미 써진 파일은 그대로 두고(반쪽
    실행), 어디까지 썼는지 보고하며, DRIFT(1)와 겹치지 않는 코드로 끝나야 한다."""
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "bad.md").write_text("> **BLUF:** 실패 문서.\n", encoding="utf-8")

    original_write_text = Path.write_text

    def _flaky_write_text(self, *args, **kwargs):
        # 쓰기는 같은 폴더 임시 파일을 거쳐 제자리 교체된다 — 실패를 심을 자리도
        # 최종 경로가 아니라 그 임시 파일이다(`_write_readme_atomically`).
        if self.parent == bad_dir and self.name.endswith(".tmp"):
            raise OSError("simulated permission denied")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _flaky_write_text)
    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])

    rc = gen_readmes.main()

    assert rc == gen_readmes.WRITE_FAILURE
    assert rc != gen_readmes.DRIFT
    err = capsys.readouterr().err
    assert "bad" in err, "실패한 파일을 보고하지 않았다"


# --- 마커 쌍이 2개 이상이면 쓰기 전에 멈춘다(파괴 경로 5) -----------------------


def test_duplicate_marker_pairs_abort_before_writing(tmp_path, monkeypatch):
    """마커 쌍(START/END)이 한 README에 두 번 나오면(병합 사고 등) 첫 쌍만
    갱신하고 둘째는 영구 방치하는 대신, 이상 상태로 보고 쓰기 전에 멈춰야 한다."""
    START, END = gen_readmes.MARK_START, gen_readmes.MARK_END
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    before = (
        "> **BLUF:** t.\n\n"
        f"{START}\n### 문서\n- `stale1.md` — 옛 항목 1.\n{END}\n\n"
        f"{START}\n### 문서\n- `stale2.md` — 옛 항목 2.\n{END}\n"
    )
    readme.write_text(before, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    assert readme.read_text(encoding="utf-8") == before, "이상 상태인데 파일을 썼다"
    assert rc == gen_readmes.DUPLICATE_MARKERS
    assert rc != 0


def test_duplicate_marker_pairs_flagged_under_check_too(tmp_path, monkeypatch):
    """--check 모드에서도 마커 쌍 중복을 '이상 없음'이라 하면 안 된다.

    **첫 쌍을 일부러 이미 최신 상태로 맞춘다** — 첫 쌍이 낡았으면 그 자체로
    DRIFT(무관한 이유)가 나 이 시나리오를 증명 못 한다(첫 쌍은 최신, 둘째 쌍만
    영구 방치라는 진짜 버그 조건을 재현해야 한다: split(...,1)은 첫 쌍만
    보므로 이 상태에서 '변경 없음'으로 보여 문제가 영원히 안 보인다)."""
    START, END = gen_readmes.MARK_START, gen_readmes.MARK_END
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")

    fresh_block = gen_readmes.build_index_block(tmp_path, [])
    single_pair = gen_readmes.compose_readme(tmp_path, fresh_block)  # 첫 쌍 = 이미 최신
    second_pair = f"{START}\n### 문서\n- `stale2.md` — 옛 항목(영구 방치돼야 하는데 안 됨).\n{END}\n"
    before = single_pair.rstrip() + "\n\n" + second_pair

    readme = tmp_path / "README.md"
    readme.write_text(before, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path), "--check"])
    rc = gen_readmes.main()

    assert rc != 0, "첫 쌍이 이미 최신이라 --check가 이상 없다고 오판했다(둘째 쌍 영구 방치를 놓침)"


# --- 쓰기가 도중에 실패해도 그 파일은 반쪽이 되지 않는다 -----------------------
#
# `write_text`는 원자적이지 않다 — 열기는 됐는데 디스크가 차거나 I/O가 끊기면
# 그 파일이 잘린 채 남는다. 이 도구는 "반쪽 실행이 제일 나쁘다"를 못박았으므로
# 파일 하나 안에서도 그게 성립해야 한다(적대 리뷰 지적).


def test_write_failure_midway_leaves_target_untouched(tmp_path, monkeypatch):
    """쓰다가 실패해도 대상 README는 옛 내용 그대로다 — 잘린 상태가 없다."""
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    before = "> **BLUF:** 폴더 설명.\n\n사람이 쓴 문단.\n"
    readme.write_text(before, encoding="utf-8")

    real_write = Path.write_text

    def fail_midway(self, data, *a, **k):
        # 임시 파일에 절반만 쓰고 터진다 — 진짜 위험 경로(쓰기 도중 실패) 재현.
        real_write(self, data[: len(data) // 2], *a, **k)
        raise OSError("디스크가 찼다(모의)")

    monkeypatch.setattr(Path, "write_text", fail_midway)
    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    monkeypatch.undo()
    assert rc == gen_readmes.WRITE_FAILURE
    assert readme.read_text(encoding="utf-8") == before, "쓰다 실패한 파일이 반쪽으로 남았다"
    leftovers = [p.name for p in tmp_path.glob(".*.tmp")]
    assert leftovers == [], f"임시 파일이 남았다: {leftovers}"


# --- 마커 짝이 안 맞는 파손 문서도 이상이다 -----------------------------------
#
# 쌍이 여럿인 경우만 막으면 START만·END만 있는 문서가 통과해, 고아 마커 뒤에 새
# 블록이 덧붙고 rc는 0이 된다 — 그 상태는 다음 실행에서야 걸리고 그 사이 커밋된다.
# (0,1)은 현실적이다: 마커를 인용부호로 감싸면 START는 줄 시작 앵커에 안 걸리고
# END만 걸린다(적대 리뷰 실측).


@pytest.mark.parametrize(
    "name,body",
    [
        ("start_only", f"> **BLUF:** 폴더.\n\n{gen_readmes.MARK_START}\n### 문서\n"),
        ("end_only", f"> **BLUF:** 폴더.\n\n### 문서\n{gen_readmes.MARK_END}\n"),
    ],
)
def test_unpaired_marker_aborts_before_writing(tmp_path, monkeypatch, name, body):
    """짝이 안 맞는 마커는 쓰기 전에 멈춘다 — 조용히 통과하면 파일이 오손된다."""
    (tmp_path / "a.md").write_text("> **BLUF:** 문서 A.\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(body, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["gen_readmes.py", "--root", str(tmp_path)])
    rc = gen_readmes.main()

    assert rc == gen_readmes.DUPLICATE_MARKERS, f"{name}: 짝 안 맞는 마커를 통과시켰다"
    assert readme.read_text(encoding="utf-8") == body, f"{name}: 멈춘다더니 썼다"


# --- build_index_block: 하위 폴더 섹션 렌더 (세 분기 — README 없음/TODO/정상 BLUF) ---
#
# 분리 전 특성화 테스트다 — 지금까지 이 갈래를 실행하는 테스트가 없었다(하위
# 디렉터리를 만드는 테스트 자체가 없었다). build_index_block을 축별 렌더 함수로
# 쪼개는 리팩토링이 이 출력을 바꾸지 않는지 고정한다.


def test_index_block_subfolder_missing_readme(tmp_path):
    """하위 폴더에 README가 없으면 '(README 없음)'로 표시한다."""
    (tmp_path / "sub").mkdir()
    block = gen_readmes.build_index_block(tmp_path, [])
    assert "- `sub/` — (README 없음)" in block


def test_index_block_subfolder_todo_bluf(tmp_path):
    """하위 폴더 README의 BLUF가 TODO면 이탤릭으로 표시한다(폴더 목적 미작성 신호)."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "README.md").write_text(
        f"> **BLUF:** {gen_readmes.TODO_PREFIX} — 목적을 채우세요.\n", encoding="utf-8"
    )
    block = gen_readmes.build_index_block(tmp_path, [])
    assert "- `sub/` — _TODO — 목적을 채우세요._" in block


def test_index_block_subfolder_normal_bluf(tmp_path):
    """하위 폴더 README에 정상 BLUF가 있으면 그 문구를 그대로 표시한다."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "README.md").write_text("> **BLUF:** 서브 폴더 설명.\n", encoding="utf-8")
    block = gen_readmes.build_index_block(tmp_path, [])
    assert "- `sub/` — 서브 폴더 설명." in block


# --- build_index_block: 아카이브 집약(`_manifest.md` 보유 폴더) -----------------
#
# 분리 전 특성화 테스트 — `_manifest.md`가 있는 폴더에서 번호매김 문서를 스킵하고
# 개수로 접는 처리를 지금까지 어떤 테스트도 덮지 않았다.


def test_index_block_archive_collapses_numbered_docs(tmp_path):
    """`_manifest.md`가 있는 폴더는 번호매김 문서(`NN-*.md`)를 개별 나열 대신
    개수로 접고, BLUF 누락으로도 잡지 않는다(색인은 _manifest.md가 대신한다)."""
    (tmp_path / "_manifest.md").write_text("색인 파일 — BLUF 없어도 무방.\n", encoding="utf-8")
    (tmp_path / "01-alpha.md").write_text("본문.\n", encoding="utf-8")
    (tmp_path / "02-beta.md").write_text("본문.\n", encoding="utf-8")

    missing: list = []
    block = gen_readmes.build_index_block(tmp_path, missing)

    assert "### 원문 수집본" in block
    assert "`NN-*.md` 2건" in block
    assert "01-alpha.md" not in block
    assert "02-beta.md" not in block
    assert missing == [], "아카이브 원문을 BLUF 누락으로 잘못 잡았다"


def test_index_block_non_archive_does_not_collapse_numbered_docs(tmp_path):
    """`_manifest.md`가 없으면 번호매김이어도 일반 문서로 개별 나열한다."""
    (tmp_path / "01-alpha.md").write_text("> **BLUF:** 알파.\n", encoding="utf-8")
    block = gen_readmes.build_index_block(tmp_path, [])
    assert "01-alpha.md` — 알파." in block
    assert "원문 수집본" not in block


# --- build_index_block: 자산 집약 경계값(_ASSET_COLLAPSE_MIN) -------------------
#
# 경계(미만/같음/초과)는 리팩토링에서 가장 잘 어긋나는 자리라 세 지점 모두 고정한다.


def test_index_block_assets_below_collapse_threshold_lists_individually(tmp_path):
    """자산 개수가 임계 미만이면 개별 파일명을 나열한다(집약 금지 경계)."""
    n = gen_readmes._ASSET_COLLAPSE_MIN - 1
    for i in range(n):
        (tmp_path / f"img{i}.png").write_bytes(b"x")
    block = gen_readmes.build_index_block(tmp_path, [])
    assert block.count("- `img") == n
    assert "*.png" not in block


def test_index_block_assets_at_collapse_threshold_collapses(tmp_path):
    """자산 개수가 임계와 같으면 집약한다(경계 포함 — `>=` 조건 고정)."""
    n = gen_readmes._ASSET_COLLAPSE_MIN
    for i in range(n):
        (tmp_path / f"img{i}.png").write_bytes(b"x")
    block = gen_readmes.build_index_block(tmp_path, [])
    assert f"- `*.png` {n}개" in block
    assert "img0.png" not in block


def test_index_block_assets_above_collapse_threshold_collapses(tmp_path):
    """자산 개수가 임계를 넘어도 계속 집약하며, 확장자당 한 줄만 남긴다."""
    n = gen_readmes._ASSET_COLLAPSE_MIN + 1
    for i in range(n):
        (tmp_path / f"img{i}.png").write_bytes(b"x")
    block = gen_readmes.build_index_block(tmp_path, [])
    assert f"- `*.png` {n}개" in block
    assert block.count("*.png") == 1


def test_index_block_missing_bluf_reported(tmp_path):
    """BLUF 없는 일반 문서가 `missing`에 실린다 — 이번 분리의 유일한 내부 계약
    변경(누락 목록을 반환형으로 바꾼 뒤 호출부가 합치는 이음매) 지점이라 그물을 둔다.

    이 배선이 끊기면 BLUF 누락이 조용히 안 보고되고, 그 상태로 --check가
    통과해 누락이 영구히 묻힌다."""
    (tmp_path / "ok.md").write_text("> **BLUF:** 요약 있음.\n", encoding="utf-8")
    (tmp_path / "no_bluf.md").write_text("요약이 없다.\n", encoding="utf-8")

    missing: list[Path] = []
    gen_readmes.build_index_block(tmp_path, missing)

    assert [p.name for p in missing] == ["no_bluf.md"]
