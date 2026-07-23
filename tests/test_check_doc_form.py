#!/usr/bin/env python3
# BLUF: check_doc_form의 폼-정본성·줄/BLUF 예산·표행/코드펜스 면제·화이트리스트·유형판정 fallback·pre-commit 배선 자기잠금방지를 무DB·무LLM으로 검증.
"""tests/test_check_doc_form.py — 문서 폼 게이트 단위테스트(무DB·무LLM).

scripts를 import하기 위해 repo 루트의 scripts 디렉토리를 sys.path에 얹는다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
import ai_harness.check_doc_form as cdf  # noqa: E402


# --- 헬퍼 -------------------------------------------------------------------
#
# doc_type()은 순수 문자열 판정(path.parts)이라 cwd와 무관하다 — 문서 경로는
# "docs/..."로 시작하는 상대경로면 된다. 반면 FORM_DIR은 (버그3 수정 후) 스크립트
# 자신의 위치에 앵커링되어 cwd와 무관하다 — 합성 폼으로 테스트하려면 cdf.FORM_DIR
# 자체를 monkeypatch해야 실제로 읽힌다(fake_repo 픽스처가 담당).

def _write_form(name: str, *, max_lines: int | None = None,
                 line_chars: int | None = None, bluf_chars: int | None = None) -> None:
    """합성 폼 파일을 cdf.FORM_DIR(현재 monkeypatch된 위치)에 쓴다. 실제 폼과
    같은 문구 관례("N줄 · 산문 한 줄 N자 · BLUF 한 줄 N자")를 쓴다 — "이하"
    접미사 없이(실제 폼 문구가 그렇다, 버그1)."""
    parts = []
    if max_lines is not None:
        parts.append(f"{max_lines}줄")
    if line_chars is not None:
        parts.append(f"산문 한 줄 {line_chars}자")
    if bluf_chars is not None:
        parts.append(f"BLUF 한 줄 {bluf_chars}자")
    cdf.FORM_DIR.mkdir(parents=True, exist_ok=True)
    (cdf.FORM_DIR / f"{name}.md").write_text(
        "<!-- 예산: " + " · ".join(parts) + "(마커 제외) -->\n", encoding="utf-8"
    )


def _write_doc(rel: str, content: str) -> Path:
    p = Path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """빈 임시 저장소로 cwd를 옮기고, FORM_DIR도 같은 임시 트리 밑으로
    monkeypatch한다. 문서 경로(doc_type 판정용)는 cwd 기준 상대경로면 되지만,
    합성 폼은 FORM_DIR을 직접 옮기지 않으면 실제 repo의 진짜 폼을 보게 된다
    (버그3 수정으로 FORM_DIR이 더는 cwd를 안 따라가므로)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cdf, "FORM_DIR", tmp_path / "docs" / "docs-format")


@pytest.fixture
def real_forms(fake_repo, monkeypatch):
    """진짜 저장소의 실제 docs/docs-format을 직접 가리킨다(읽기 전용이라 복사
    불필요) — 실제 예산(100줄·80자·100자)으로 검증하는 테스트용. cwd는 여전히
    fake_repo가 옮긴 무관한 임시 디렉터리 그대로다 — 이 자체가 버그3(FORM_DIR이
    CWD 상대였던 결함)의 직접 회귀 증거: cwd가 repo와 무관해도 FORM_DIR이
    스크립트 위치를 앵커로 옳게 찾아야 아래 테스트들이 통과한다."""
    monkeypatch.setattr(cdf, "FORM_DIR", _REPO_ROOT / "src" / "ai_harness" / "docs_format")


@pytest.fixture
def with_extra_marker(real_forms, monkeypatch):
    """`gate_config.EXTRA_AUTOGEN_MARKERS`가 두 번째 마커 쌍(`app:managed`류)을
    채웠다고 가정하고 돌린다 — 이 저장소 자신은 그런 도구가 없어 실제로는
    비어 있지만(핵심 값이 core에 없어야 하는 이유는 gate_config.py 참고), "마커가
    여럿일 때 core 로직(교차 검출·프로즈 인용 방어 등)이 옳게 동작하는가"는
    이 저장소의 실제 설정과 무관하게 검증해야 한다. `cdf._AUTOGEN_MARKERS`는
    모듈 임포트 시점에 굳어(gate_config 값을 나중에 바꿔도 소급 안 됨) 파생된
    세 속성(`_AUTOGEN_MARKERS`·`_AUTOGEN_START`·`_AUTOGEN_END`)을 함께
    monkeypatch한다."""
    markers = cdf._AUTOGEN_MARKERS + (("app:managed:begin", "app:managed:end"),)
    monkeypatch.setattr(cdf, "_AUTOGEN_MARKERS", markers)
    monkeypatch.setattr(
        cdf, "_AUTOGEN_START",
        re.compile(r"^\s*<!--\s*(?:" + "|".join(re.escape(s) for s, _ in markers) + ")"),
    )
    monkeypatch.setattr(
        cdf, "_AUTOGEN_END",
        re.compile(r"^\s*<!--\s*(?:" + "|".join(re.escape(e) for _, e in markers) + ")"),
    )


# --- 제1성질: 폼이 정본이다(하드코딩 아님) ------------------------------------

def test_form_budget_is_canonical_not_hardcoded(fake_repo):
    """폼 파일의 수치를 바꾸면 검사기 판정이 따라 바뀐다 — 예산이 코드에
    하드코딩돼 있지 않다는 증명(이 설계의 핵심, 제일 중요한 테스트)."""
    _write_form("widget", line_chars=10)
    doc = _write_doc("docs/widget/x.md", "가" * 15 + "\n")

    assert cdf.check_file(doc) != []  # 예산 10자에 15자 줄 — 리젝

    _write_form("widget", line_chars=20)  # 같은 문서, 폼 수치만 올림
    assert cdf.check_file(doc) == []  # 이제 통과 — 판정이 폼을 따라갔다


# --- 버그3: FORM_DIR 경로 앵커 · 폼 부재 fail-closed --------------------------
#
# 감독이 직접 재현한 결함: FORM_DIR이 CWD 상대라 다른 디렉터리에서 실행하면
# 폼을 못 찾고, load_budgets가 빈 dict를 반환해 예산이 전부 None이 되어 검사를
# 통째로 건너뛰고 조용히 통과했다("위반이 없어서"가 아니라 "잴 자가 없어서").

def test_cwd_independent_verdict_regression(tmp_path, monkeypatch):
    """같은 파일, CWD만 달라도 같은 판정이 나와야 한다(이번 결함의 직접 회귀).
    FORM_DIR이 스크립트 자신의 위치를 앵커로 쓰면 무관한 CWD에서도 폼을 찾는다."""
    doc = tmp_path / "outside.md"
    doc.write_text(("가" * 200) + "\n", encoding="utf-8")

    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)  # repo와 전혀 무관한 CWD(FORM_DIR은 그대로 real)

    violations = cdf.check_file(doc)
    assert violations != []
    assert not any("예산을 하나도 못 뽑음" in v for v in violations)  # 자를 제대로 찾았다


def test_missing_form_dir_fails_closed_not_open(tmp_path, monkeypatch):
    """폼 디렉터리 자체가 없으면(FORM_DIR이 가리키는 곳이 깨졌거나 폼이 통째로
    안 배포됐거나) 조용히 통과가 아니라 큰 소리로 리젝해야 한다(fail-closed).
    검사기 자체의 부재(훅 래퍼가 fail-open으로 처리하는 층)와는 다른 층이다."""
    monkeypatch.setattr(cdf, "FORM_DIR", tmp_path / "nonexistent-forms")
    doc = tmp_path / "x.md"
    doc.write_text("아무 문서\n", encoding="utf-8")

    violations = cdf.check_file(doc)
    assert violations != []
    assert any("예산을 하나도 못 뽑음" in v for v in violations)


def test_empty_form_dir_fails_closed(tmp_path, monkeypatch):
    """폼 디렉터리는 있지만 전역 폴백(rules.md)이 없으면 마찬가지로 리젝한다."""
    empty_dir = tmp_path / "docs-format"
    empty_dir.mkdir()
    monkeypatch.setattr(cdf, "FORM_DIR", empty_dir)
    doc = tmp_path / "x.md"
    doc.write_text("아무 문서\n", encoding="utf-8")

    violations = cdf.check_file(doc)
    assert violations != []
    assert any("예산을 하나도 못 뽑음" in v for v in violations)


# --- 문서 100줄 예산 ---------------------------------------------------------

def test_over_line_budget_rejected(real_forms):
    doc = _write_doc("docs/rules/x.md", "x\n" * 101)
    violations = cdf.check_file(doc)
    assert any("101줄 > 100줄" in v for v in violations)


def test_within_line_budget_passes(real_forms):
    """경계 포함: 정확히 100줄(+표준 후행 개행)은 통과해야 한다.

    회귀(버그2): split("\\n")은 후행 개행이 있는 표준 파일에서 팬텀 빈 줄을
    하나 더 세어 실제 100줄 문서를 101줄로 오탐 리젝했다. splitlines()로 고쳤다.
    """
    doc = _write_doc("docs/rules/x.md", "x\n" * 100)
    assert cdf.check_file(doc) == []


def test_empty_file_passes_without_crash(real_forms):
    doc = _write_doc("docs/rules/x.md", "")
    assert cdf.check_file(doc) == []


def test_autogen_block_not_counted_in_line_budget(real_forms):
    """자동생성 블록은 총량에서 빼야 한다 — 저자가 손댈 수 없는 몫이다.

    줄 **길이**는 이미 면제하면서 **총량**만 세면, 게이트가 "쪼개거나 근거를
    history로 내려라"라고 하는데 저자는 둘 다 할 수 없다(그 줄들은 gen_readmes가
    각 문서 BLUF에서 생성한다). 그 BLUF는 원본 문서에서 이미 예산 대상이라,
    총량에 또 세는 것은 같은 텍스트를 두 번 규제하는 것이다.
    """
    autogen = (
        "<!-- BLUF-INDEX:START — auto-generated by scripts/gen_readmes.py -->\n"
        + "- `a.md` — 한 줄.\n" * 50
        + "<!-- BLUF-INDEX:END -->\n"
    )
    doc = _write_doc("docs/rules/x.md", "x\n" * 60 + autogen)
    assert cdf.check_file(doc) == []


def test_authored_lines_still_counted_around_autogen_block(real_forms):
    """면제는 블록 안에만 적용된다 — 블록 밖 저자 산문은 그대로 센다."""
    autogen = (
        "<!-- BLUF-INDEX:START -->\n"
        + "- `a.md` — 한 줄.\n" * 50
        + "<!-- BLUF-INDEX:END -->\n"
    )
    doc = _write_doc("docs/rules/x.md", "x\n" * 101 + autogen)
    violations = cdf.check_file(doc)
    assert any("101줄 > 100줄" in v for v in violations)


def test_app_managed_block_also_exempt_from_line_budget(with_extra_marker):
    """`app:managed` 블록도 자동생성이다 — 온보딩 스크립트가 멱등 splice한다.

    이 마커가 면제 밖이면, 온보딩 스크립트가 블록을 갱신할 때 기계가 만든 줄 때문에
    pre-commit이 기계가 만든 커밋을 리젝한다. BLUF-INDEX가 겪던 것과 같은 병리다.
    """
    managed = (
        "<!-- app:managed:begin -->\n"
        + "관리 블록 줄.\n" * 50
        + "<!-- app:managed:end -->\n"
    )
    doc = _write_doc("docs/rules/x.md", "x\n" * 60 + managed)
    assert cdf.check_file(doc) == []


def test_app_managed_block_exempt_from_prose_rules(with_extra_marker):
    """관리 블록 안 산문은 문장·길이 규칙에서도 면제된다 — 저자가 못 고친다.

    실증: AGENTS.md의 app:managed 블록이 "문장이 여럿" 위반을 내고 있었다.
    """
    managed = (
        "<!-- app:managed:begin -->\n"
        "첫 문장이다. 같은 줄에 둘째 문장도 있다. 셋째도 있다.\n"
        "<!-- app:managed:end -->\n"
    )
    doc = _write_doc("docs/rules/x.md", "x\n" * 10 + managed)
    assert cdf.check_file(doc) == []


def test_marker_quoted_in_prose_does_not_open_a_block(with_extra_marker):
    """프로즈 안의 마커 인용은 블록 시작이 아니다.

    실사고: 설계 문서가 본문에서 `<!-- app:managed:begin/end -->`를 인용했는데,
    부분일치 정규식이 이를 블록 시작으로 읽어 파일 끝까지 면제했다 — 위반이
    조용히 숨었다. 코드펜스 미닫힘은 렌더가 깨져 저자가 알아채지만, HTML 주석은
    렌더에 안 보여 아무 신호가 없다.
    """
    doc = _write_doc(
        "docs/rules/x.md",
        "마커 `<!-- app:managed:begin -->`를 쓴다고 설명하는 줄이다.\n" + "가" * 90 + "\n",
    )
    violations = cdf.check_file(doc)
    assert any("90자 > 80자" in v for v in violations)


def test_crossed_autogen_markers_fail_toward_stricter(with_extra_marker):
    """마커가 교차 중첩되면 짝이 어긋난다 — 더 엄격한 쪽으로 실패함을 못박는다.

    토글이 단일 불리언이라 마커 종류를 구분하지 않는다. 바깥이 먼저 닫히면
    아직 자동생성 구간인 줄이 저자 산문으로 검사당한다. 우회가 아니라
    과잉엄격 방향이라 안전한 실패다 — 현재 동작을 명문화해 리팩터가 이걸
    반대 방향(면제가 새는 쪽)으로 바꾸지 못하게 한다.
    """
    doc = _write_doc(
        "docs/rules/x.md",
        "<!-- BLUF-INDEX:START -->\n"
        "<!-- app:managed:begin -->\n"
        "<!-- BLUF-INDEX:END -->\n"
        + "가" * 90 + "\n"
        "<!-- app:managed:end -->\n",
    )
    violations = cdf.check_file(doc)
    assert any("90자 > 80자" in v for v in violations)


def test_unclosed_autogen_block_counts_to_eof(real_forms):
    """닫히지 않은 블록은 EOF까지 면제된다 — 면제 자체가 새는 것보다 낫다.

    다만 이 동작이 우연이 아님을 못박는다: 마커를 열어두면 그 아래는 안 센다.
    """
    doc = _write_doc("docs/rules/x.md", "x\n" * 60 + "<!-- BLUF-INDEX:START -->\n" + "y\n" * 100)
    assert cdf.check_file(doc) == []


# --- 산문 한 줄 80자 예산 -----------------------------------------------------

def test_prose_over_char_budget_rejected_with_file_and_line(real_forms):
    doc = _write_doc("docs/rules/x.md", "짧다\n" + ("가" * 81) + "\n짧다\n")
    violations = cdf.check_file(doc)
    assert any(f"{doc}:2:" in v for v in violations)
    assert any("81자 > 80자" in v for v in violations)


def test_prose_char_budget_boundary_is_inclusive(real_forms):
    """정확히 80자는 통과 — 경계에서 한 글자 차이로 리젝되면 안 된다."""
    doc = _write_doc("docs/rules/x.md", ("가" * 80) + "\n")
    assert cdf.check_file(doc) == []


# --- 검증 참조 면제의 상한 — 면제는 "못 쪼개는 것"에만 -------------------------
#
# 결정표(스팬 = `[✅ …]`·`[⚠️ …]`·`[🔴 …]` 매칭 전체 길이):
#
#   스팬 길이         | 면제 | 근거
#   ------------------|------|--------------------------------------------------
#   <= line_max       | 예   | 원래 취지 — 테스트 함수명은 쪼개면 깨진다
#   == line_max       | 예   | 경계 포함(줄 길이 판정이 `>`로 리젝하는 것과 동형)
#   == line_max + 1   | 아니오 | 산문 예산을 넘긴 것은 더는 "못 쪼개는 것"이 아니다
#   > line_max        | 아니오 | 대괄호가 80자 상한의 우회 통로가 되는 것을 막는다
#   line_max 미파싱   | 예   | 잴 자가 없으면 면제를 거둘 근거도 없다(기존 동작)
#
# 임계값은 새 매직넘버가 아니라 **그 문서 유형의 산문 예산 line_max 재사용**이다.

def _review_ref(total_len: int, marker: str = "✅") -> str:
    """길이가 정확히 total_len인 검증 참조 스팬을 만든다(대괄호·마커 포함)."""
    span = f"[{marker} " + "가" * (total_len - len(f"[{marker} ]")) + "]"
    assert len(span) == total_len
    return span


def test_long_review_ref_span_is_not_exempt(real_forms):
    """대괄호 안에 산문을 넣어 80자 상한을 우회하던 통로를 막는다(이슈 72).

    실측: 한 문서의 한 줄이 원본에서 산문 예산을 넘겼는데 검증 참조를 빼면
    40자가 되어 통과했다. 스팬 자체가 산문 예산을 넘으면 면제하지 않는다.
    """
    span = _review_ref(200, marker="⚠️")
    doc = _write_doc("docs/features/x.md", "짧은 서술 " + span + "\n")
    violations = cdf.check_file(doc)
    assert any("자 > 80자" in v for v in violations)


def test_short_review_ref_span_still_exempt(real_forms):
    """회귀: 80자 이하 참조(테스트 함수명)는 계속 면제된다 — 면제의 원래 몫."""
    line = ("가" * 60) + " [✅ test_store_reconcile.py::test_reconcile_deletes_stale]"
    assert len(line) > 80  # 면제가 없으면 리젝될 줄이다
    doc = _write_doc("docs/features/x.md", line + "\n")
    assert cdf.check_file(doc) == []


def test_review_ref_exemption_boundary_at_line_max(real_forms):
    """경계: 스팬이 정확히 line_max(80)면 면제, 81자면 면제 아님."""
    exact = _write_doc("docs/features/a.md", ("가" * 5) + _review_ref(80) + "\n")
    assert cdf.check_file(exact) == []

    over = _write_doc("docs/features/b.md", ("가" * 5) + _review_ref(81) + "\n")
    assert any("86자 > 80자" in v for v in cdf.check_file(over))


def test_review_ref_exemption_threshold_follows_the_form_not_a_constant(fake_repo):
    """임계값은 하드코딩 80이 아니라 그 유형의 line_max다 — 폼을 바꾸면 따라간다."""
    # 접두 산문 15자는 두 예산(20·40) 모두를 지킨다 — 판정을 가르는 건 스팬뿐이다.
    doc_text = ("가" * 15) + _review_ref(30) + "\n"

    _write_form("widget", line_chars=20)
    doc = _write_doc("docs/widget/x.md", doc_text)
    assert cdf.check_file(doc) != []  # 스팬 30자 > 예산 20자 → 면제 없음, 45자로 리젝

    _write_form("widget", line_chars=40)  # 같은 문서, 폼 수치만 올림
    assert cdf.check_file(doc) == []  # 스팬 30자 <= 40자 → 다시 면제, 15자로 통과


def test_multiple_review_ref_spans_judged_independently(real_forms):
    """한 줄에 짧은 참조와 긴 참조가 섞이면 각 스팬을 **독립** 판정한다(#72 후속).

    `_strip_review_refs`는 `_REVIEW_REF.sub`의 매치별 콜백이라 스팬마다 line_max로
    따로 잰다 — 짧은 참조(<=80)는 벗겨져 면제되고, 긴 참조(>80)는 산문으로 남아
    측정된다. 한 스팬이 길다고 같은 줄의 다른(짧은) 스팬 면제까지 걷히지 않음을
    고정한다(둘을 뭉뚱그려 전부 남기거나 전부 벗기면 이 테스트가 red).
    """
    short = "[✅ " + "가" * 10 + "]"   # 스팬 <= 80 → 면제(벗겨짐)
    long = "[⚠️ " + "가" * 200 + "]"   # 스팬 > 80 → 면제 박탈(남음)
    assert len(short) <= 80 and len(long) > 80
    line = "머리 " + short + " 산문 " + long
    stripped = cdf._strip_review_refs(line, 80)
    assert short not in stripped   # 짧은 스팬: 면제
    assert long in stripped        # 긴 스팬: 면제 박탈 — 독립 판정의 직접 증거
    # 통합: 남은 긴 스팬이 줄을 80자 초과로 만들어 리젝된다(짧은 스팬은 면제라 미측정).
    doc = _write_doc("docs/features/x.md", line + "\n")
    assert any("자 > 80자" in v for v in cdf.check_file(doc))


# --- 한 줄 한 문장(문장 종결 마침표) — 80자와 별개 축 -------------------------

def test_multiple_sentences_in_one_line_rejected(real_forms):
    """한 줄에 문장 종결 '. '가 있으면 여러 문장이므로 리젝한다."""
    doc = _write_doc("docs/rules/x.md", "짧다\n한 문장이다. 두 번째가 붙었다.\n짧다\n")
    violations = cdf.check_file(doc)
    assert any("문장이 여럿" in v for v in violations)
    assert any(f"{doc}:2:" in v for v in violations)


def test_sentence_rule_excludes_decimals_paths_numbers(real_forms):
    """오탐 방지: 소수(0.85)·코드 경로(config.py)·번호 리스트(1. )·줄끝
    마침표는 문장 종결이 아니다 — 마침표 앞이 숫자거나 뒤가 공백이 아니면
    안 걸린다."""
    body = (
        "소수 0.85 값을 쓴다\n"
        "config.py 경로를 참조한다\n"
        "1. 번호 리스트 항목이다\n"
        "한 문장이 줄 끝에서 끝난다.\n"
    )
    doc = _write_doc("docs/rules/x.md", body)
    sentence_violations = [v for v in cdf.check_file(doc) if "문장이 여럿" in v]
    assert sentence_violations == []


def test_heading_exempt_from_sentence_rule(real_forms):
    """헤딩(`## A. 환경`)의 `A.`는 문장 끝이 아니다 — 구조 라벨이라 문장
    규칙에서 뺀다. 숫자 라벨과 달리 문자 라벨은 앞자리 숫자 배제로 안 걸러진다."""
    body = "## A. 환경/인프라\n짧다\n### B. 문서 구조\n짧다\n"
    doc = _write_doc("docs/rules/x.md", body)
    sentence_violations = [v for v in cdf.check_file(doc) if "문장이 여럿" in v]
    assert sentence_violations == []


def test_heading_still_bound_by_line_length(real_forms):
    """헤딩은 문장 규칙만 면제다 — 길이 예산은 그대로 진다(라벨은 짧아야 한다)."""
    doc = _write_doc("docs/rules/x.md", "## " + ("가" * 90) + "\n")
    length_violations = [v for v in cdf.check_file(doc) if "80자" in v]
    assert length_violations != []


# --- 좌표(줄번호) 게이트 — 현재상태 문서만 -----------------------------------

def test_coordinate_rejected_in_features(real_forms):
    """현재상태 문서(features)의 손으로 친 줄번호 좌표는 리젝된다."""
    doc = _write_doc("docs/features/x.md", "짧다\n소스는 `config.py:168`이다\n")
    coord = [v for v in cdf.check_file(doc) if "좌표" in v]
    assert coord != []
    assert any("config.py:168" in v for v in coord)


def test_coordinate_rejected_in_rules_current_state(real_forms):
    """현재상태 문서는 features만이 아니다 — rules도 좌표를 리젝한다(denylist)."""
    doc = _write_doc("docs/rules/x.md", "짧다\n소스는 `config.py:168`이다\n")
    assert [v for v in cdf.check_file(doc) if "좌표" in v] != []


def test_coordinate_exempt_in_dated_records(real_forms):
    """날짜 박힌 기록(adr·history·review·test)의 줄번호는 그 시점 기록이라 면제."""
    for rel in ("docs/adr/x.md", "docs/history/B-x.md",
                "docs/review/x.md", "docs/test/x.md"):
        doc = _write_doc(rel, "짧다\n결정 시점 `graph.py:347`\n")
        assert [v for v in cdf.check_file(doc) if "좌표" in v] == []


def test_coordinate_gate_ignores_urls_timestamps_symbols(real_forms):
    """오탐 방지: URL·타임스탬프·심볼(::)·SHA경로는 좌표가 아니다."""
    body = (
        "서버는 `localhost:8765`에 뜬다\n"
        "로그 시각 16:55에 찍혔다\n"
        "진입은 `cli.py::main`이다\n"
        "확인 `git show abc123:docs/x.md`\n"
    )
    doc = _write_doc("docs/features/x.md", body)
    assert [v for v in cdf.check_file(doc) if "좌표" in v] == []


# --- diff 스코프(--staged): 손댄 줄만 강제 -----------------------------------

def _rungit(*args):
    # 주의: 이 파일 하단에 `_git(repo, *args)`가 따로 있어 이름이 겹친다.
    # 파이썬은 나중 정의로 덮으므로 CWD 기준 헬퍼는 다른 이름을 쓴다.
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _seed_repo(rel, content):
    """tmp cwd에 git 레포를 만들고 파일을 커밋한다(diff base 확보)."""
    _rungit("init", "-q")
    _rungit("config", "user.email", "t@t")
    _rungit("config", "user.name", "t")
    doc = _write_doc(rel, content)
    _rungit("add", rel)
    _rungit("commit", "-qm", "seed")
    return doc


def test_staged_scopes_to_changed_lines_not_whole_file(real_forms):
    """진행형의 핵심: 기존 위반 줄은 유예하고 이번에 추가/변경한 줄만 리젝한다.
    한 줄 고치려 문서 전체 재정합을 강요하던 캐스케이드를 끊는다."""
    long = "가" * 90  # 80자 초과
    doc = _seed_repo("docs/rules/x.md", f"짧다\n{long}\n짧다\n")
    doc.write_text(f"짧다\n{long}\n{long}\n짧다\n", encoding="utf-8")  # 새 위반 줄 삽입
    _rungit("add", "docs/rules/x.md")
    staged = cdf.check_staged(doc)
    assert len(staged) == 1                    # 이번에 추가한 줄만
    assert "80자" in staged[0]
    assert len([v for v in cdf.check_file(doc) if "80자" in v]) == 2  # 전체는 둘 다 본다


def test_staged_passes_when_fixing_unrelated_line(real_forms):
    """기존 위반 문서에서 위반과 무관한 한 줄만 고치면(새 위반 0) 통과한다."""
    long = "가" * 90
    doc = _seed_repo("docs/rules/x.md", f"원래 짧다\n{long}\n짧다\n")
    doc.write_text(f"고친 짧은 줄\n{long}\n짧다\n", encoding="utf-8")  # 1번째 줄만 수정
    _rungit("add", "docs/rules/x.md")
    assert cdf.check_staged(doc) == []         # 기존 LONG 줄은 유예


def test_staged_new_file_fully_checked(real_forms):
    """새 파일은 모든 줄이 '추가'라 전량 검사된다(신규는 완전 준수)."""
    long = "가" * 90
    _rungit("init", "-q")
    _rungit("config", "user.email", "t@t")
    _rungit("config", "user.name", "t")
    doc = _write_doc("docs/rules/new.md", f"짧다\n{long}\n")
    _rungit("add", "docs/rules/new.md")
    assert any("80자" in v for v in cdf.check_staged(doc))


def test_staged_linecount_only_on_net_add(fake_repo):
    """줄수 초과는 이번 변경이 순증(문자 추가>삭제)일 때만 — 순수 치환(문자수도
    그대로인 교체)이면 유예한다.

    데이터 변경 내역: 예전엔 "a"→"a2"(줄 순증 0이지만 **문자는 +1**)였다.
    판정 축을 줄→문자로 바꾸면 그 데이터는 더 이상 "순수 치환"이 아니라 문자가
    실제로 는 사례가 되어 이 테스트가 깨진다(검증하려는 불변 자체가 아니라
    낡은 축의 우연한 데이터였다는 뜻). "a"→"z"로 바꿔 줄·문자 순증이 모두
    0인 진짜 치환으로 고쳤다 — 검증 대상(치환은 유예)은 그대로다.
    """
    _write_form("rules", max_lines=3, line_chars=80)
    doc = _seed_repo("docs/rules/x.md", "a\nb\nc\nd\n")  # 4줄 = 예산 3 초과
    doc.write_text("z\nb\nc\nd\n", encoding="utf-8")   # 순수 치환 — 줄수도 문자수도 순증 0
    _rungit("add", "docs/rules/x.md")
    assert not any("비대" in v for v in cdf.check_staged(doc))


# --- 총량 판정 축: 줄 순증 → 문자 순증 ----------------------------------------
#
# 두 규칙이 서로를 배반했다: 규칙 A(한 줄 한 문장)를 지켜 긴 줄을 문장마다
# 쪼개면 내용은 그대로인데 줄만 는다. 그런데 총량(규칙 B) 판정이 "줄 순증"
# 기준이면, 규칙 A를 지킨 사람이 규칙 B의 위반을 뒤집어쓴다(실사고: 편집 전부터
# 초과였던 문서 3건이 쪼개기만으로 줄이 늘어 총량 위반이 되살아났다). 줄 수는
# 포맷의 함수이고 문자 수는 내용의 함수이므로, "문서가 비대해졌다"는 문자가
# 늘었을 때만 참이어야 한다.

def test_staged_bloat_not_reported_when_split_only_replaces_separators_with_newlines(fake_repo):
    """쪼개기: 줄은 늘어도(1→4) 문자 수는 그대로(단어 사이 공백이 개행으로
    바뀔 뿐)면 총량 초과를 보고하지 않는다 — 줄 순증 기준이면 이 케이스가
    오탐이던 실사고 그 자체다."""
    _write_form("rules", max_lines=3, line_chars=80)
    doc = _seed_repo("docs/rules/x.md", "가나다 라마바 사아자 자차카\n")  # 1줄, 예산3 이내
    doc.write_text("가나다\n라마바\n사아자\n자차카\n", encoding="utf-8")  # 4줄>예산3, 문자수는 안 늘어남
    _rungit("add", "docs/rules/x.md")
    assert not any("비대" in v for v in cdf.check_staged(doc))


def test_staged_bloat_reported_when_content_actually_grows(fake_repo):
    """내용 추가: 줄도 늘고 문자 수도 크게 늘면(새 문장 추가) 총량 초과를
    보고한다 — 진짜 비대해진 경우까지 유예하면 게이트가 무력화된다."""
    _write_form("rules", max_lines=3, line_chars=80)
    doc = _seed_repo("docs/rules/x.md", "가나다\n")  # 1줄
    doc.write_text(
        "가나다\n"
        "완전히 새로 추가한 문장이다\n"
        "또 다른 새 문장도 추가했다\n"
        "넷째 줄도 새로 늘었다\n",
        encoding="utf-8",
    )  # 4줄>예산3, 문자 수도 크게 증가
    _rungit("add", "docs/rules/x.md")
    assert any("비대" in v for v in cdf.check_staged(doc))


def test_staged_bloat_not_reported_on_pure_deletion_even_if_still_over_budget(fake_repo):
    """회귀 고정: 순수 삭제(줄이 줄었지만 여전히 예산 초과)는 기존처럼 보고
    안 한다 — 판정 축을 줄에서 문자로 바꿔도 이 동작은 깨지면 안 된다."""
    _write_form("rules", max_lines=3, line_chars=80)
    doc = _seed_repo("docs/rules/x.md", "a\nb\nc\nd\ne\n")  # 5줄, 이미 예산3 초과
    doc.write_text("a\nb\nc\nd\n", encoding="utf-8")  # 1줄 삭제, 4줄(여전히 초과) — 순수 삭제
    _rungit("add", "docs/rules/x.md")
    assert not any("비대" in v for v in cdf.check_staged(doc))


def test_staged_reads_index_not_worktree(real_forms):
    """스테이징 후 워킹트리를 더 고쳐 줄번호가 어긋나도, 커밋될 내용(인덱스)의
    위반을 잡는다. 워킹트리를 읽으면 좌표계가 갈라져 fail-open(적대검증 재현)."""
    long = "가" * 90
    doc = _seed_repo("docs/rules/x.md", "짧다\n짧다\n")
    doc.write_text(f"짧다\n{long}\n짧다\n", encoding="utf-8")  # 인덱스: LONG=2번째 줄
    _rungit("add", "docs/rules/x.md")
    # 재-스테이징 없이 워킹트리 앞에 2줄 추가 → 워킹트리에선 LONG이 4번째 줄로 밀림
    doc.write_text(f"머리\n앞\n짧다\n{long}\n짧다\n", encoding="utf-8")
    staged = cdf.check_staged(doc)
    # 인덱스(커밋될 내용)의 LONG 위반을 잡아야 한다 — 워킹트리 좌표로 놓치면 fail-open
    assert any("80자" in v for v in staged)


def test_staged_line_delta_counts_dash_content(real_forms):
    """삭제 콘텐츠가 `---`(수평선)이어도 삭제로 센다 — 파일헤더 `--- a/path`와
    콘텐츠를 접두어로 구별하면 언더카운트(적대검증 버그1)."""
    doc = _seed_repo("docs/rules/x.md", "머리\n---\n본문\n")
    doc.write_text("본문\n", encoding="utf-8")  # '머리'와 '---' 2줄 순삭제
    _rungit("add", "docs/rules/x.md")
    _added, removed = cdf.staged_line_delta(doc)
    assert removed == 2  # '---'도 삭제로 세야(접두어 아니라 위치로 판정)


def test_shared_hunk_parser_classifies_dash_content_across_both_deltas(real_forms):
    """staged_line_delta·staged_char_delta가 공유하는 헌크 파서의 세 분기(@@ 헤더 /
    `+`줄 / `-`줄)를 한 diff로 전부 태우고, 두 원본 독스트링이 명시한 엣지케이스—
    삭제 콘텐츠가 문자 그대로 `---`(수평선)일 때 파일헤더 `--- a/path`로 오분류되면
    안 된다—를 **두 소비 함수 양쪽에서** 명시적으로 단언한다(공유 헬퍼 추출 회귀 락).

    시나리오: 'keep' 유지 + '---'·'gone' 순삭제 + 'addN' 신규추가. `---`가 헤더로
    오분류되면 removed·removed_chars가 언더카운트돼 두 단언이 동시에 깨진다."""
    doc = _seed_repo("docs/rules/x.md", "keep\n---\ngone\n")
    doc.write_text("keep\naddN\n", encoding="utf-8")  # '---'·'gone' 삭제, 'addN' 추가
    _rungit("add", "docs/rules/x.md")

    # (1) 줄 델타: `+`줄(추가) 1개 + `-`줄(삭제) 2개 — '---'도 삭제로 세야(위치 판정).
    added, removed = cdf.staged_line_delta(doc)
    assert removed == 2, "'---'가 헤더로 오분류돼 삭제 언더카운트(접두어 판정 회귀)"
    assert 2 in added, "신규줄 'addN'이 신규-파일 줄번호 2로 잡혀야(헤더의 +2)"

    # (2) 문자 델타: 같은 파서로 각 줄 콘텐츠 길이 합산 — 추가 4('addN') - 삭제 7
    # ('---' 3 + 'gone' 4). '---'가 헤더면 삭제 3자를 놓쳐 델타가 0이 된다.
    assert cdf.staged_char_delta(doc) == len("addN") - (len("---") + len("gone"))


def test_staged_added_line_starting_with_plus_is_checked(real_forms):
    """새로 친 위반 줄의 콘텐츠가 `++`로 시작해도(diff에서 `+++`) 검사한다 —
    접두어 판정이면 false negative로 새는 축(적대검증 버그1)."""
    doc = _seed_repo("docs/rules/x.md", "짧다\n")
    doc.write_text("짧다\n" + "++" + "가" * 90 + "\n", encoding="utf-8")  # 92자, ++시작
    _rungit("add", "docs/rules/x.md")
    assert any("80자" in v for v in cdf.check_staged(doc))


def test_staged_rename_not_bypassed(real_forms):
    """개명+작은 편집을 한 커밋에 해도 게이트가 통째로 새면 안 된다(적대검증 버그2).
    ACM 필터는 R(개명)을 빼 개명 파일이 우회됐다 — ACMR + 옛/새 경로로 잡는다.
    편집이 작아야 git이 rename으로 판정(바이트 유사도)하므로 짧은 좌표 위반을 쓴다."""
    base = "".join(f"줄{i}\n" for i in range(60))  # 큰 파일 → 유사도 높아 R 판정
    _seed_repo("docs/features/old.md", base)  # features = 좌표 게이트 대상
    _rungit("mv", "docs/features/old.md", "docs/features/new.md")
    Path("docs/features/new.md").write_text(base + "소스 `config.py:5`.\n", encoding="utf-8")
    _rungit("add", "docs/features/new.md")
    files = cdf.staged_files()
    md = [(n, o) for n, o in files if n.as_posix().endswith("new.md")]
    assert md, "개명 파일이 staged 목록에 있어야 한다(ACMR)"
    new, old = md[0]
    assert old is not None and old.as_posix().endswith("old.md")  # rename 감지·옛경로 확보
    assert any("좌표" in v for v in cdf.check_staged(new, old))  # 새 좌표 위반 잡힘


# --- 표 행·코드펜스 면제 ------------------------------------------------------

def test_table_row_exempt_from_line_length(real_forms):
    long_row = "|" + "가" * 90 + "|\n"
    doc = _write_doc("docs/rules/x.md", long_row)
    assert cdf.check_file(doc) == []


def test_line_starting_with_pipe_but_not_real_table_is_still_exempt(real_forms):
    """설계상 '|'로 시작하면 무조건 표 행 취급한다 — 진짜 마크다운 표(헤더
    구분행 등)인지는 안 따진다(의도된 단순 휴리스틱, 팀 브리핑 그대로)."""
    not_really_a_table = "|" + "그냥 파이프로 시작하는 줄일 뿐이다 " * 5 + "\n"
    doc = _write_doc("docs/rules/x.md", not_really_a_table)
    assert cdf.check_file(doc) == []


def test_code_fence_content_exempt_from_line_length(real_forms):
    content = "```\n" + ("x" * 90) + "\n```\n"
    doc = _write_doc("docs/rules/x.md", content)
    assert cdf.check_file(doc) == []


def test_fence_toggle_reactivates_check_after_close(real_forms):
    """닫는 펜스 이후엔 검사가 다시 걸려야 한다 — 토글이 정확히 짝을 맞춘다."""
    content = "```\n" + ("x" * 90) + "\n```\n" + ("가" * 90) + "\n"
    doc = _write_doc("docs/rules/x.md", content)
    violations = cdf.check_file(doc)
    assert any(f"{doc}:4:" in v for v in violations)


def test_unclosed_fence_exempts_rest_of_file(real_forms):
    """펜스가 안 닫히면 토글이 다시 안 꺼져 이후 전부가 면제된다 — 현재
    토글 설계의 알려진 결과를 고정한다(수정 대상 아님, 팀 브리핑: 설계 불변)."""
    content = "```\n" + ("가" * 90) + "\n"  # 닫는 펜스 없음
    doc = _write_doc("docs/rules/x.md", content)
    assert cdf.check_file(doc) == []


# --- 마크다운 링크 URL 길이 면제 ---------------------------------------------
# 결정테이블(축: URL길이·라벨길이·URL내공백·문장수):
#   URL길다·라벨짧다·공백없음  → 길이 통과(면제)          [지금 RED]
#   라벨길다·URL짧다           → 길이 리젝(라벨=산문)       [이미 통과·과잉면제 방지]
#   괄호에 공백(가짜 URL)      → 길이 리젝(공백=쪼갤수 있음) [이미 통과·바이패스 차단]
#   URL길다 + 두 문장          → 길이 통과 & 문장 리젝(별개축) [길이 RED / 문장 불변]

def test_markdown_link_url_exempt_from_line_length(real_forms):
    """URL(괄호부)은 안 쪼개지는 경로라 길이에서 뺀다 — 라벨/산문이 짧으면 통과.
    수정 전엔 원문 전체가 80자를 넘어 리젝(RED), URL 면제 후 통과(GREEN)."""
    url = "../history/verification-integrity/" + "seg/" * 25 + "doc.md"  # 경로 >80
    line = f"[설계 근거]({url}) 참조.\n"
    assert len(line.rstrip("\n")) > 80, "전제: 원문 자체는 80자 초과(면제 없으면 RED)"
    doc = _write_doc("docs/rules/x.md", line)
    assert cdf.check_file(doc) == []  # URL 면제로 길이·문장·좌표 전부 무위반


def test_markdown_link_long_label_still_rejected(real_forms):
    """라벨(대괄호부)은 산문이라 그대로 산입 — URL만 면제. 라벨이 길면 여전히 리젝
    (URL 면제가 '라벨도 면제'로 과잉확장되지 않는다는 대조 케이스)."""
    line = f"[{'가' * 90}](../a.md)\n"  # 라벨 90자, URL 짧음
    doc = _write_doc("docs/rules/x.md", line)
    assert any("> 80자" in v for v in cdf.check_file(doc))


def test_markdown_link_url_with_spaces_not_exempt(real_forms):
    """괄호 안에 공백이 있으면 안 쪼개지는 경로가 아니라(공백에서 쪼갤 수 있고
    렌더도 깨진다) 산문 — 면제 자격 없음. 괄호를 산문 우회 통로로 못 쓴다."""
    fake_url = "가 " * 60  # 공백 다수·>80, 진짜 URL 아님
    line = f"[x]({fake_url.strip()})\n"
    doc = _write_doc("docs/rules/x.md", line)
    assert any("> 80자" in v for v in cdf.check_file(doc))


def test_link_url_length_exempt_does_not_disable_sentence_check(real_forms):
    """URL 길이 면제는 길이 축만 손댄다 — 같은 줄의 '한 줄 두 문장'은 여전히 잡힌다.
    (measured 분리 검증: 길이는 URL 벗긴 사본으로, 문장은 원본 measured로 잰다.)"""
    long_url = "../" + "seg/" * 25 + "d.md"  # >80
    line = f"첫 문장이다. 둘째 문장 [l]({long_url}).\n"
    doc = _write_doc("docs/rules/x.md", line)
    violations = cdf.check_file(doc)
    assert not any("> 80자" in v for v in violations)   # 길이: URL 면제로 통과
    assert any("문장이 여럿" in v for v in violations)   # 문장: 원본 기준 그대로 걸림


# --- BLUF 한 줄 100자 예산 ----------------------------------------------------

def test_bluf_over_budget_rejected(real_forms):
    doc = _write_doc("docs/rules/x.md", "> **BLUF:** " + ("가" * 101) + "\n")
    violations = cdf.check_file(doc)
    assert any("BLUF" in v and "101자 > 100자" in v for v in violations)


def test_bluf_marker_prefix_not_counted(real_forms):
    """마커 `> **BLUF:** ` 자체 길이는 100자 예산에 안 들어간다 — 정확히
    100자 본문(마커 제외)은 통과해야 한다."""
    doc = _write_doc("docs/rules/x.md", "> **BLUF:** " + ("가" * 100) + "\n")
    assert cdf.check_file(doc) == []


# --- WHITELIST ---------------------------------------------------------------

def test_whitelisted_path_is_exempt(real_forms, monkeypatch):
    doc = _write_doc("docs/rules/x.md", ("가" * 200) + "\n")
    assert cdf.check_file(doc) != []  # 화이트리스트 전이면 리젝됨을 먼저 확인
    monkeypatch.setattr(cdf, "WHITELIST", frozenset({doc.as_posix()}))
    assert cdf.check_file(doc) == []


def test_whitelist_defaults_to_empty():
    """WHITELIST는 비어 있는 게 기본 — 면제 문서 없음(의도된 상태).
    누군가 조용히 항목을 미리 채워두면 이 테스트가 깨진다."""
    assert cdf.WHITELIST == frozenset()


# --- 유형 판정 · 폼 없는 유형의 fallback --------------------------------------

def test_type_without_own_form_falls_back_to_global(real_forms):
    doc = _write_doc("docs/guide/x.md", ("가" * 81) + "\n")
    assert cdf.doc_type(doc) == "guide"
    assert cdf.load_budgets("guide") == {}  # guide.md 폼 자체가 없다
    violations = cdf.check_file(doc)
    assert any("81자 > 80자" in v for v in violations)  # rules.md 폴백이 걸었다


def test_agent_definition_path_has_its_own_type(real_forms):
    """`.claude/agents/*.md`는 유형 판정을 받아야 한다 — 전에는 None이라 rules
    전역 폴백으로 **우연히** 떨어졌다(이슈 60). 우연은 근거가 아니다."""
    assert cdf.doc_type(Path(".claude/agents/reviewer.md")) == "agent-def"


def test_agent_definition_nested_in_another_repo_is_deferred_not_supported(real_forms):
    """중첩 저장소의 `<하위 저장소>/.claude/agents/`는 **의도적으로** 유형이 아니다.

    `docs/<유형>/` 갈래와 대칭으로 경로 맨 앞만 본다. "어디서든" 스캔하는 쪽이
    더 넓지만 활성 사례가 0이라 유예했다 — 실측 근거:

    - pre-commit은 언제나 자기 저장소 루트(`git rev-parse --show-toplevel`)
      기준으로만 --staged를 돈다. 하위 저장소는 별개 저장소라 각자 훅이 각자 루트다.
    - 다른 레포 트리가 중첩되는 경로(예: 미러 클론)는 보통 .gitignore
      대상이라 --staged가 못 본다.
    - doc_type()/check_file()을 그런 경로로 부르는 코드가 없다(호출자 0건).

    이 테스트가 깨지는 날 = 위치-무관 스캔을 재도입한 날이다. 그때는 위 세 근거가
    아직 유효한지부터 확인하고 이 테스트를 뒤집어라(기각이 아니라 유예다).
    """
    assert cdf.doc_type(Path("subrepos/foo/.claude/agents/x.md")) is None
    assert cdf.doc_type(Path("/abs/checkout/.claude/agents/x.md")) is None


def test_existing_type_branches_not_broken_by_agent_def(real_forms):
    """회귀: 기존 두 갈래(docs/<유형>/ · _AGENT_CONFIG_NAMES)는 그대로다."""
    assert cdf.doc_type(Path("docs/rules/08-doc-authoring-norms.md")) == "rules"
    assert cdf.doc_type(Path("docs/features/x.md")) == "features"
    assert cdf.doc_type(Path("AGENTS.md")) == "agents"
    assert cdf.doc_type(Path("CLAUDE.md")) == "agents"
    assert cdf.doc_type(Path(".claude/settings.json")) is None
    assert cdf.doc_type(Path("README.md")) is None


def test_doc_type_segment_boundaries():
    """`doc_type()` 세그먼트 수 경계 결정표 — off-by-one·깊은 중첩 고정(#96-4).

    두 갈래(docs/<유형>/… · .claude/agents/…)는 **경로 맨 앞만** 본다. 경계:

      경로                        | 세그먼트 | 유형       | 근거
      ----------------------------|---------|------------|-----------------------------
      `.claude/agents`            | 2       | None       | agent-def는 `>=3` 필요(파일명 없음)
      `.claude/agents/x.md`       | 3       | agent-def  | 최소 성립 경계(off-by-one 하한)
      `.claude/agents/sub/deep.md`| 4(중첩) | agent-def  | parts[:2]만 봄 — 깊이 무관
      `docs`                      | 1       | None       | docs 갈래는 `>=2` 필요
      `docs/rules`                | 2       | rules      | 유형 디렉터리(파일명 없어도 판정)
      `docs/rules/sub/deep/x.md`  | 5(중첩) | rules      | parts[1]이 유형 — 깊이 무관

    doc_type은 순수 문자열 판정(path.parts)이라 폼/cwd에 무관 → 픽스처 불요.
    """
    assert cdf.doc_type(Path(".claude/agents")) is None           # 2세그먼트: 파일명 없음
    assert cdf.doc_type(Path(".claude/agents/x.md")) == "agent-def"   # 3세그먼트 하한
    assert cdf.doc_type(Path(".claude/agents/sub/deep.md")) == "agent-def"  # 깊은 중첩
    assert cdf.doc_type(Path("docs")) is None                     # 1세그먼트: 유형 없음
    assert cdf.doc_type(Path("docs/rules")) == "rules"            # 2세그먼트: 유형 디렉터리
    assert cdf.doc_type(Path("docs/rules/sub/deep/x.md")) == "rules"  # 깊은 중첩


def test_agent_def_uses_own_form_not_rules_fallback(real_forms):
    """통합: 유형 판정이 실제 폼(docs/docs-format/agent-def.md)에 물린다.

    수치를 여기 옮겨 적지 않는다(폼이 정본) — 대신 "빈 dict가 아니고 rules
    폴백과 다른 값"임을 본다. 같은 수치를 쓰면 폼이 갈라진 의미가 없다.
    """
    budgets = cdf.load_budgets("agent-def")
    assert budgets != {}
    assert budgets["max_lines"] != cdf.load_budgets("rules")["max_lines"]


def test_agent_def_line_budget_applies_end_to_end(real_forms):
    """판정→폼→검사가 실제로 이어진다: rules(100줄)로는 걸릴 줄 수가
    agent-def(110줄) 예산에서는 통과한다."""
    n = cdf.load_budgets("rules")["max_lines"] + 1  # rules 상한 초과, agent-def 이내
    body = "---\nname: x\n---\n" + "짧다\n" * (n - 3)

    agent_def = _write_doc(".claude/agents/x.md", body)
    assert [v for v in cdf.check_file(agent_def) if "줄 — 문서가 비대하다" in v] == []

    as_rules = _write_doc("docs/rules/x.md", body)
    assert [v for v in cdf.check_file(as_rules) if "줄 — 문서가 비대하다" in v] != []


def test_type_specific_form_overrides_fallback(fake_repo):
    """유형 전용 폼이 있으면 그 수치가 이긴다 — 폴백(_GLOBAL_FORM=rules)보다
    우선한다."""
    _write_form("rules", line_chars=80)   # 전역 폴백(느슨)
    _write_form("widget", line_chars=10)  # 유형 전용(빡빡)

    doc = _write_doc("docs/widget/x.md", ("가" * 15) + "\n")
    violations = cdf.check_file(doc)
    assert any("15자 > 10자" in v for v in violations)  # 폴백(80) 아니라 유형(10)


# --- main() exit code ---------------------------------------------------------

def test_main_with_no_targets_returns_zero():
    assert cdf.main([]) == 0


def test_main_exit_zero_when_clean(real_forms):
    doc = _write_doc("docs/rules/x.md", "짧다\n")
    assert cdf.main([str(doc)]) == 0


def test_main_exit_one_when_violations(real_forms):
    doc = _write_doc("docs/rules/x.md", ("가" * 200) + "\n")
    assert cdf.main([str(doc)]) == 1


# --- --staged 모드 ------------------------------------------------------------
#
# staged_markdown()은 실제 git 인덱스(git diff --cached)를 읽으므로 유닛테스트가
# 아니라 실제 git repo가 필요하다.

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")  # 호스트 전역설정 격리


def _copy_forms(repo: Path) -> None:
    shutil.copytree(_REPO_ROOT / "src" / "ai_harness" / "docs_format", repo / "docs" / "docs-format")


def _run_staged(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ai-harness", "check-doc", "--staged"],
        cwd=repo, capture_output=True, text=True,
    )


def test_staged_with_zero_staged_md_passes(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "note.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "note.txt")
    result = _run_staged(repo)
    assert result.returncode == 0


def test_staged_only_checks_staged_not_unstaged_md(tmp_path):
    """스테이징 안 된(기존 위반) 문서는 안 걸린다 — 손대는 문서부터 폼에
    맞춘다는 설계(안 그러면 기존 위반 문서 전부가 커밋을 막는다)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _copy_forms(repo)
    (repo / "docs" / "rules").mkdir(parents=True)
    (repo / "docs" / "rules" / "good.md").write_text("짧다\n", encoding="utf-8")
    _git(repo, "add", "docs/rules/good.md")
    # bad.md는 위반이지만 스테이징 안 됨(untracked로 방치)
    (repo / "docs" / "rules" / "bad.md").write_text(("가" * 200) + "\n", encoding="utf-8")

    result = _run_staged(repo)
    assert result.returncode == 0


def test_staged_rejects_when_staged_md_violates(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _copy_forms(repo)
    (repo / "docs" / "rules").mkdir(parents=True)
    (repo / "docs" / "rules" / "bad.md").write_text(("가" * 200) + "\n", encoding="utf-8")
    _git(repo, "add", "docs/rules/bad.md")

    result = _run_staged(repo)
    assert result.returncode == 1


# --- pre-commit 배선(git 훅) 자체 회귀 ----------------------------------------
#
# 유닛테스트가 아니라 **커밋되는 hooks/pre-commit 그 자체**를 실행한다 —
# check_pr_body의 settings.json 쉘 한 줄과 동형 위험: 검사기 부재 시 훅이
# 죽으면 저장소의 모든 커밋이 막힌다(게이트가 자기 자신을 잠금).

def _install_precommit_hook(repo: Path) -> None:
    """실제 커밋되는 hooks/pre-commit을 .git/hooks/로 복사·chmod +x —
    scripts/install_hooks.py가 하는 것과 동일한 조작을 그대로 실행한다."""
    dst = repo / ".git" / "hooks" / "pre-commit"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_REPO_ROOT / "src" / "ai_harness" / "hooks" / "pre-commit", dst)
    dst.chmod(dst.stat().st_mode | 0o111)


def _commit_doc(repo: Path, rel_path: str, content: str) -> subprocess.CompletedProcess:
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    return _git(repo, "commit", "-q", "-m", "test")


def _commit_doc_no_cli(repo: Path, rel_path: str, content: str) -> subprocess.CompletedProcess:
    """`ai-harness` 가 PATH에 없을 때(=미설치) 커밋 — 훅이 fail-open 하는지 검증용.

    venv bin을 뺀 PATH(`/usr/bin:/bin`)로 `git commit` 을 돌려, 훅의
    `command -v ai-harness` 가 실패해 게이트가 건너뛰는지 재현한다."""
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", rel_path], capture_output=True, text=True)
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "test"],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def wired_repo(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _install_precommit_hook(repo)
    # 이 테스트들은 doc-form 게이트만 본다 — gen-readmes(모든 repo에 root README를
    # 요구)는 대상 gate_config로 끈다(소비자 opt-out 경로도 함께 검증).
    (repo / "gate_config.py").write_text(
        'DISABLED_GATES = ("gen-readmes",)\n', encoding="utf-8"
    )
    return repo


def test_wired_hook_blocks_bad_doc(wired_repo):
    result = _commit_doc(wired_repo, "docs/rules/x.md", ("가" * 90) + "\n")
    assert result.returncode != 0
    assert "리젝" in result.stdout + result.stderr


def test_wired_hook_allows_good_doc(wired_repo):
    result = _commit_doc(wired_repo, "docs/rules/x.md", "짧다\n")
    assert result.returncode == 0


def test_wired_hook_allows_unrelated_non_md_commit(wired_repo):
    result = _commit_doc(wired_repo, "README.txt", "hello\n")
    assert result.returncode == 0


def test_wired_hook_does_not_lock_repo_when_checker_absent(wired_repo):
    """검사기가 없으면 게이트는 꺼지되 저장소를 잠그지는 않는다.

    check_pr_body의 동명 회귀(test_wired_hook_does_not_lock_repo_when_checker_absent)와
    같은 성질: 파일 부재는 git에서 보이는 문제이므로, 전 커밋을 막는 것보다
    게이트가 조용히 꺼지는 편이 덜 해롭다. ai-harness 가 PATH에 없으면
    (미설치) 위반감 문서를 커밋해도 통과해야 한다.
    """
    result = _commit_doc_no_cli(wired_repo, "docs/rules/x.md", ("가" * 200) + "\n")
    assert result.returncode == 0


# --- YAML frontmatter 면제 --------------------------------------------------
#
# 에이전트 정의(.claude/agents/*.md)는 frontmatter가 필수인데 YAML 스칼라는
# 줄바꿈이 불가하다 — 저자가 형식을 고를 수 없는 영역이라 자동생성 블록과 같은
# 논리로 면제한다. 파일별 화이트리스트로 때우면 정의를 추가할 때마다 재발한다.

def test_frontmatter_exempt_from_line_rules(real_forms):
    """frontmatter 안의 긴 줄·여러 문장은 위반이 아니다 — YAML은 못 접는다."""
    doc = _write_doc(
        "docs/rules/x.md",
        "---\n"
        f"description: {'가' * 200}. 두 번째 문장이다.\n"
        "tools: Read, Glob, Grep, Bash, Write, Agent, SendMessage, TeamCreate\n"
        "---\n"
        "짧다\n",
    )
    assert cdf.check_file(doc) == []


def test_body_after_frontmatter_still_checked(real_forms):
    """면제는 닫는 `---`에서 끝난다 — 본문은 그대로 잰다."""
    doc = _write_doc(
        "docs/rules/x.md",
        "---\n"
        "name: x\n"
        "---\n"
        + ("가" * 200) + "\n",
    )
    assert any("자 > " in v for v in cdf.check_file(doc))


def test_horizontal_rule_does_not_open_frontmatter(real_forms):
    """본문 중간의 수평선 `---`은 frontmatter를 열지 않는다.

    자동생성 마커가 부분일치라 본문 인용부터 파일 끝까지 면제돼 위반이
    숨었던 실사고와 같은 부류다 — 여는 자리를 파일 첫 줄로 못 박지 않으면
    수평선 하나가 나머지 문서 전체의 게이트를 끈다.
    """
    doc = _write_doc(
        "docs/rules/x.md",
        "제목\n"
        "\n"
        "---\n"
        + ("가" * 200) + "\n",
    )
    assert any("자 > " in v for v in cdf.check_file(doc))
