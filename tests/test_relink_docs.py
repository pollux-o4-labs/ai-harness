# BLUF: relink_docs의 링크 재작성(rewrite)·깨진 링크 스캔(--check)·main 인자 분기를 검증.
"""tests/test_relink_docs.py — 문서 재편 링크 재작성기 단위테스트.

rewrite는 `git ls-files`로 추적 대상을 뽑으므로 유닛테스트가 아니라 실제 git
repo가 필요하다(test_check_doc_form.py의 --staged 시험과 같은 사정).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import ai_harness.relink_docs as relink_docs

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")


def _write(repo: Path, rel: str, content: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# --- normalize / relpath — 순수 함수 -----------------------------------------


def test_normalize_collapses_dot_segments():
    assert relink_docs.normalize("docs/a/../b/./c.md") == "docs/b/c.md"


def test_normalize_drops_leading_dotdot_beyond_root():
    """앞에 접어낼 세그먼트가 없는 선행 `..`는 조용히 버려진다(레포 루트를
    벗어나는 `..`가 크래시로 이어지지 않는다)."""
    assert relink_docs.normalize("../a.md") == "a.md"


def test_relpath_climbs_to_common_ancestor():
    assert relink_docs.relpath("docs/adr/x.md", "docs/rules") == "../adr/x.md"


def test_relpath_same_dir_is_bare_filename():
    assert relink_docs.relpath("docs/a.md", "docs") == "a.md"


# --- rewrite — 인바운드 링크(이동 대상을 가리킴) ------------------------------


def test_rewrite_updates_inbound_link_to_moved_file(tmp_path):
    """다른 문서가 이동 대상을 가리키던 링크는 새 경로로 갱신된다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/rules/a.md", "옛 위치.\n")
    _write(repo, "docs/index.md", "[규칙](rules/a.md) 참고.\n")
    _git(repo, "add", "-A")

    # git mv 시뮬레이션: 파일을 새 위치로 옮긴 뒤(테스트에선 write+삭제) move_map을 준다.
    (repo / "docs" / "rules" / "a.md").unlink()
    _write(repo, "docs/rules/topic/a.md", "옛 위치.\n")
    _git(repo, "add", "-A")

    move_map = {"docs/rules/a.md": "docs/rules/topic/a.md"}
    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps(move_map), encoding="utf-8")

    rc = relink_docs.cmd_rewrite(repo, str(move_map_path))
    assert rc == 0
    assert "[규칙](rules/topic/a.md)" in (repo / "docs" / "index.md").read_text(encoding="utf-8")


def test_rewrite_adjusts_outbound_link_from_moved_file(tmp_path):
    """이동한 파일 자신이 비이동 대상을 가리키던 링크는 깊어진 만큼 `../`가 늘어난다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/rules/a.md", "[색인](../index.md) 참고.\n")
    _write(repo, "docs/index.md", "색인.\n")
    _git(repo, "add", "-A")

    (repo / "docs" / "rules" / "a.md").unlink()
    _write(repo, "docs/rules/topic/a.md", "[색인](../index.md) 참고.\n")
    _git(repo, "add", "-A")

    move_map = {"docs/rules/a.md": "docs/rules/topic/a.md"}
    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps(move_map), encoding="utf-8")

    rc = relink_docs.cmd_rewrite(repo, str(move_map_path))
    assert rc == 0
    assert "[색인](../../index.md)" in (repo / "docs" / "rules" / "topic" / "a.md").read_text(
        encoding="utf-8"
    )


def test_rewrite_leaves_untouched_link_unchanged(tmp_path):
    """소스도 타깃도 안 움직인 링크는 무의미 churn 없이 그대로 둔다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "[b](b.md) 참고.\n")
    _write(repo, "docs/b.md", "b.\n")
    _git(repo, "add", "-A")

    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps({}), encoding="utf-8")

    rc = relink_docs.cmd_rewrite(repo, str(move_map_path))
    assert rc == 0
    assert (repo / "docs" / "a.md").read_text(encoding="utf-8") == "[b](b.md) 참고.\n"


def test_rewrite_skips_links_inside_fenced_code_block(tmp_path):
    """계약(모듈 docstring): 좁은 정규식 파서는 펜스(```/~~~) 안을 링크 대상에서
    제외한다 — 코드 예제 안의 `[label](target)` 텍스트까지 문서 링크로 오인해
    재작성하면 코드 예제 내용이 깨진다."""
    f = tmp_path / "a.md"
    f.write_text(
        "본문.\n"
        "```\n"
        "[규칙](rules/a.md) 예제\n"
        "```\n"
        "[규칙](rules/a.md) 실제 링크.\n",
        encoding="utf-8",
    )
    move_map = {"rules/a.md": "rules/topic/a.md"}

    changed = relink_docs.rewrite_file(f, "a.md", "a.md", move_map)

    assert changed == 1
    text = f.read_text(encoding="utf-8")
    assert "[규칙](rules/a.md) 예제" in text  # 펜스 안 — 무변경
    assert "[규칙](rules/topic/a.md) 실제 링크." in text  # 펜스 밖 — 재작성


def test_rewrite_file_returns_zero_when_recomputed_target_is_unchanged(tmp_path):
    """파일 자신이 이동했어도(s_old != s_new) 재계산한 상대경로 문자열이 원래와
    같으면(같은 디렉터리 내 개명 등) 무의미한 재작성으로 세지 않는다 — 이동 여부
    early-return(같은 디렉터리·비이동 대상)과는 다른 경로로, 실제로 새 타깃을
    계산까지 한 뒤에 우연히 같아지는 경우다."""
    f = tmp_path / "a2.md"
    f.write_text("[b](b.md) 참고.\n", encoding="utf-8")

    changed = relink_docs.rewrite_file(f, "docs/a.md", "docs/a2.md", {})

    assert changed == 0
    assert f.read_text(encoding="utf-8") == "[b](b.md) 참고.\n"


def test_rewrite_skips_external_and_anchor_only_links(tmp_path):
    """외부 URL과 앵커 전용(`#foo`) 링크는 경로 파싱 대상이 아니므로 무변경이다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = "[외부](https://example.com/x) · [앵커](#절) 참고.\n"
    _write(repo, "docs/a.md", content)
    _git(repo, "add", "-A")

    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps({"docs/a.md": "docs/moved/a.md"}), encoding="utf-8")

    rc = relink_docs.cmd_rewrite(repo, str(move_map_path))
    assert rc == 0
    assert (repo / "docs" / "a.md").read_text(encoding="utf-8") == content


# --- --check — 깨진 상대링크 스캔 --------------------------------------------


def test_check_detects_broken_relative_link(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    # --check의 대상은 `./`·`../`로 시작하는 상대경로 타깃뿐이다(같은 폴더 베어
    # 파일명은 이 스캐너의 범위 밖 — 원본 설계 그대로 유지).
    _write(repo, "docs/a.md", "[사라짐](./missing.md) 참고.\n")
    _git(repo, "add", "-A")

    rc = relink_docs.cmd_check(repo)
    assert rc == 1


def test_check_passes_when_no_broken_links(tmp_path):
    """`./`로 시작해 스캐너가 실제로 채점하는 타깃인데 대상이 존재하는 경우 —
    베어 파일명(`b.md`)은 스캐너 범위 밖이라 이 분기를 안 태운다(위
    test_check_detects_broken_relative_link의 주석 참조)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "[존재](./b.md) 참고.\n")
    _write(repo, "docs/b.md", "b.\n")
    _git(repo, "add", "-A")

    rc = relink_docs.cmd_check(repo)
    assert rc == 0


def test_check_catches_soft_wrapped_link_that_rewrite_misses(tmp_path):
    """라벨과 타깃이 다른 줄에 걸친 소프트랩 링크는 rewrite가 놓치지만
    --check는 라벨 무관 정규식이라 깨진 타깃을 잡는다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "[사라짐\n](./missing.md) 참고.\n")
    _git(repo, "add", "-A")

    rc = relink_docs.cmd_check(repo)
    assert rc == 1


# --- 비ASCII·특수문자 파일명 회귀 --------------------------------------------
#
# `git ls-files`의 기본(개행 구분) 출력은 이런 이름을 C 방식으로 quote한다.
# quote를 안 풀고 그 문자열을 그대로 경로로 열면 존재하지 않는 경로가 되어
# 크래시한다(회귀 원본: 형제 저장소는 문서가 대부분 한글 이름).


def test_check_survives_non_ascii_filename(tmp_path):
    """한글 등 비ASCII 파일명이 있어도 죽지 않고 정상 판정한다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/한글문서.md", "[존재](./b.md) 참고.\n")
    _write(repo, "docs/b.md", "b.\n")
    _git(repo, "add", "-A")

    rc = relink_docs.cmd_check(repo)
    assert rc == 0


def test_check_survives_filename_with_tab(tmp_path):
    """탭이 든 파일명은 `core.quotepath=false`로도 안 풀린다(그 설정은 비ASCII
    전용) — `-z`라 애초에 quote가 없어 이 이름도 그대로 살아남는다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    weird = repo / "docs" / "a\tb.md"
    weird.parent.mkdir(parents=True, exist_ok=True)
    weird.write_text("[존재](./b.md) 참고.\n", encoding="utf-8")
    _write(repo, "docs/b.md", "b.\n")
    _git(repo, "add", "-A")

    rc = relink_docs.cmd_check(repo)
    assert rc == 0


def test_rewrite_survives_non_ascii_filename(tmp_path):
    """이동 대상 자체가 비ASCII 파일명이어도 rewrite가 죽지 않고 인바운드
    링크를 정상 재작성한다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/rules/한글문서.md", "옛 위치.\n")
    _write(repo, "docs/index.md", "[규칙](rules/한글문서.md) 참고.\n")
    _git(repo, "add", "-A")

    (repo / "docs" / "rules" / "한글문서.md").unlink()
    _write(repo, "docs/rules/topic/한글문서.md", "옛 위치.\n")
    _git(repo, "add", "-A")

    move_map = {"docs/rules/한글문서.md": "docs/rules/topic/한글문서.md"}
    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps(move_map, ensure_ascii=False), encoding="utf-8")

    rc = relink_docs.cmd_rewrite(repo, str(move_map_path))
    assert rc == 0
    assert "[규칙](rules/topic/한글문서.md)" in (repo / "docs" / "index.md").read_text(
        encoding="utf-8"
    )


# --- main — 인자 분기 ---------------------------------------------------------


def test_main_check_mode_dispatches_to_cmd_check(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "[사라짐](./missing.md) 참고.\n")
    _git(repo, "add", "-A")

    assert relink_docs.main(["--root", str(repo), "--check"]) == 1


def test_main_rewrite_mode_dispatches_to_cmd_rewrite(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "그대로.\n")
    _git(repo, "add", "-A")
    move_map_path = tmp_path / "move_map.json"
    move_map_path.write_text(json.dumps({}), encoding="utf-8")

    assert relink_docs.main(["--root", str(repo), str(move_map_path)]) == 0


def test_main_errors_when_neither_check_nor_move_map(tmp_path):
    """--check도 MOVE_MAP_JSON도 없으면 argparse가 exit 2로 종료한다."""
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        relink_docs.main(["--root", str(tmp_path)])
    assert exc_info.value.code == 2


# --- 스크립트로 직접 실행 ------------------------------------------------------


def test_run_as_script_via_dunder_main(tmp_path):
    """`python -m ai_harness.relink_docs`로 직접 돌리는 경로 — 설치된 `ai-harness`
    콘솔 스크립트(cli.py 라우팅)를 거치지 않고 `if __name__ == "__main__"` 블록
    자체가 main()을 부르고 그 반환값으로 프로세스가 종료하는지 검증한다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "docs/a.md", "[존재](./b.md) 참고.\n")
    _write(repo, "docs/b.md", "b.\n")
    _git(repo, "add", "-A")

    result = subprocess.run(
        [sys.executable, "-m", "ai_harness.relink_docs", "--root", str(repo), "--check"],
        capture_output=True, text=True,
    )

    assert result.returncode == 0
    assert "깨진 상대링크: 0" in result.stdout
