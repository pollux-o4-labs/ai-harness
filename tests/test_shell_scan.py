"""셸 명령 토큰화·세그먼트 분할 — 두 게이트가 공유하는 판정."""
from __future__ import annotations

import pytest

from ai_harness import shell_scan as ss


# ── 토큰화 ───────────────────────────────────────────────────────────────────
# 공백 분리 토크나이저로는 못 가르는 형태만 모은다. 그 형태가 실사고를 냈다.


@pytest.mark.parametrize("command,expected", [
    ("git reset --hard; git clean -fd", ["git", "reset", "--hard", ";", "git", "clean", "-fd"]),
    ("git reset --hard;git clean -fd", ["git", "reset", "--hard", ";", "git", "clean", "-fd"]),
    ("a && b", ["a", "&&", "b"]),
    ("a&&b", ["a", "&&", "b"]),
    ("a & b", ["a", "&", "b"]),
])
def test_operators_are_separate_tokens(command, expected):
    assert ss.tokenize(command) == expected


def test_quoted_operator_is_preserved():
    """따옴표 안 연산자는 문자다 — 경계가 아니다."""
    assert ss.tokenize('git commit -m "fix: a; b"') == ["git", "commit", "-m", "fix: a; b"]


def test_comment_is_dropped():
    """`#` 이후는 주석이다 — 평문 속 명령어가 호출로 오인되지 않는다."""
    assert ss.tokenize("echo start\n# git reset --hard\necho end") == [
        "echo", "start", "echo", "end",
    ]


def test_unclosed_quote_raises():
    """정책 중립 — 예외를 삼키지 않고 호출자에게 올린다."""
    with pytest.raises(ValueError):
        ss.tokenize('git commit -m "unclosed')


# ── 세그먼트 분할 ────────────────────────────────────────────────────────────


def test_split_drops_operator_tokens():
    assert ss.split_segments(["a", "&&", "b", ";", "c"]) == [["a"], ["b"], ["c"]]


def test_split_ignores_empty_segments():
    """연산자가 잇달아 와도 빈 세그먼트를 만들지 않는다."""
    assert ss.split_segments(["&&", "a", ";", ";", "b"]) == [["a"], ["b"]]


def test_split_without_operators_is_single_segment():
    assert ss.split_segments(["git", "status"]) == [["git", "status"]]


def test_single_ampersand_is_a_boundary():
    """두 게이트가 각자 집합을 두었을 때 한쪽에만 `&`가 있어 판정이 갈렸다."""
    assert "&" in ss.SHELL_OPERATORS
    assert ss.split_segments(["a", "&", "b"]) == [["a"], ["b"]]
