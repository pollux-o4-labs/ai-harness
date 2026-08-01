# BLUF: marker_splice(gen_readmes·gen_agents_common 공유 splice 유틸)의 탐색·추출·교체·원자적 쓰기를 독립적으로 검증.
"""tests/test_marker_splice.py — 공유 마커 splice 유틸 단위테스트.

gen_readmes.py·gen_agents_common.py 양쪽에서 재사용되는 지점이므로, 두 소비
모듈의 회귀(tests/test_gen_readmes_guard.py·test_gen_agents_common.py)와
별개로 이 모듈 자체의 계약을 여기서 고정한다.

DB도 LLM(언어모델)도 안 쓴다.
"""
from __future__ import annotations

import pytest

from ai_harness import marker_splice as ms

START, END = "X:START", "X:END"


@pytest.fixture
def markers():
    return ms.compile_markers(START, END)


def test_marker_occurrences_zero_when_absent(markers):
    assert ms.marker_occurrences("아무 글.\n", *markers) == (0, 0)


def test_marker_occurrences_one_one_for_complete_pair(markers):
    content = f"머리말.\n{START}\n본문.\n{END}\n"
    assert ms.marker_occurrences(content, *markers) == (1, 1)


def test_marker_occurrences_counts_duplicates(markers):
    content = f"{START}\nA\n{END}\n{START}\nB\n{END}\n"
    assert ms.marker_occurrences(content, *markers) == (2, 2)


def test_marker_prose_mention_mid_line_does_not_count(markers):
    """줄 시작이 아닌 마커 인용은 안 걸린다 — 줄 시작 앵커가 핵심."""
    content = f"이 도구는 `{START}`를 찍는다.\n"
    assert ms.marker_occurrences(content, *markers) == (0, 0)


def test_extract_block_returns_inner_text(markers):
    content = f"머리말.\n{START}\n본문 줄.\n{END}\n꼬리말.\n"
    inner = ms.extract_block(content, *markers)
    assert inner is not None
    assert "본문 줄." in inner
    assert "머리말" not in inner
    assert "꼬리말" not in inner


def test_extract_block_none_when_start_missing(markers):
    assert ms.extract_block(f"본문.\n{END}\n", *markers) is None


def test_extract_block_none_when_end_missing(markers):
    assert ms.extract_block(f"{START}\n본문.\n", *markers) is None


def test_splice_replaces_existing_pair_and_keeps_surroundings(markers):
    content = f"머리말.\n\n{START}\n낡은 내용.\n{END}\n\n꼬리말.\n"
    new_block = f"{START}\n새 내용.\n{END}"
    result = ms.splice(content, new_block, *markers)
    assert "머리말." in result
    assert "꼬리말." in result
    assert "새 내용." in result
    assert "낡은 내용." not in result


def test_splice_appends_when_no_pair_present(markers):
    content = "머리말만 있다.\n"
    new_block = f"{START}\n새 내용.\n{END}"
    result = ms.splice(content, new_block, *markers)
    assert result.startswith("머리말만 있다.")
    assert result.rstrip("\n").endswith(END)


def test_splice_is_idempotent(markers):
    content = "머리말.\n"
    new_block = f"{START}\n내용.\n{END}"
    once = ms.splice(content, new_block, *markers)
    twice = ms.splice(once, new_block, *markers)
    assert once == twice


# --- write_atomically: 원자적 교체·실패 시 임시 파일 청소 -------------------


def test_write_atomically_writes_content(tmp_path):
    target = tmp_path / "f.txt"
    ms.write_atomically(target, "내용\n")
    assert target.read_text(encoding="utf-8") == "내용\n"


def test_write_atomically_uses_lf(tmp_path):
    target = tmp_path / "f.txt"
    ms.write_atomically(target, "줄1\n줄2\n")
    assert b"\r\n" not in target.read_bytes()


def test_write_atomically_leaves_no_tmp_file_on_success(tmp_path):
    target = tmp_path / "f.txt"
    ms.write_atomically(target, "내용\n")
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == []


def test_write_atomically_cleans_up_tmp_and_reraises_on_failure(tmp_path):
    target = tmp_path / "f.txt"

    def _boom(path, content):
        raise OSError("simulated failure")

    with pytest.raises(OSError):
        ms.write_atomically(target, "내용\n", write=_boom)

    assert not target.exists()
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == []


def test_write_atomically_custom_write_is_used(tmp_path):
    """`write` 인자를 넘기면 기본 `write_lf` 대신 그걸 쓴다 — 호출측 모듈이
    자기 전역 이름을 통해 넘기면 테스트가 그 이름을 monkeypatch할 수 있다."""
    target = tmp_path / "f.txt"
    calls = []

    def _record(path, content):
        calls.append((path, content))
        ms.write_lf(path, content)

    ms.write_atomically(target, "내용\n", write=_record)
    assert len(calls) == 1
    assert target.read_text(encoding="utf-8") == "내용\n"
