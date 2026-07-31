# BLUF: gate_config.rule_cite의 공란/값-존재 토글 계약을 검증.
"""tests/test_gate_config.py — 레포별 설정(gate_config.py) 단위테스트.

DB도 LLM(언어모델)도 안 쓴다 — 순수 문자열 판정이라 어디서 돌려도 같은 결과다.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
import ai_harness.gate_config as gc  # noqa: E402


def test_rule_cite_empty_base_yields_empty_string():
    """base가 공란(규칙 문서 없는 저장소의 기본값)이면 인용이 통째로 생략된다."""
    assert gc.rule_cite("", "제3조") == ""


def test_rule_cite_with_article():
    assert gc.rule_cite("스타일 규칙", "3항") == "(스타일 규칙 3항)"


def test_rule_cite_without_article():
    """article 생략 시 base만 괄호에 담긴다."""
    assert gc.rule_cite("스타일 규칙") == "(스타일 규칙)"


def test_extra_whitelist_defaults_to_empty():
    """대상 저장소가 등재하지 않으면 core 판정에 아무 영향이 없어야 한다."""
    assert gc.EXTRA_WHITELIST == frozenset()


def test_extra_whitelist_is_in_public_surface():
    """__all__에 없으면 config.py의 오버레이가 이 값을 조용히 무시한다
    (gate_config.py 모듈 주석의 계약) — 등재 자체를 회귀로 고정한다."""
    assert "EXTRA_WHITELIST" in gc.__all__
