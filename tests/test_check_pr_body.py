# BLUF: check_pr_body의 섹션 필수·섹션별 예산·면제 섹션 형태·은어 풀이·gh 명령 본문추출·훅 exit코드·코멘트 게이트·머지 준비 dry-run을 검증.
"""tests/test_check_pr_body.py — PR 본문 게이트 단위테스트.

DB도 LLM(언어모델)도 안 쓴다 — 순수 문자열 판정이라 어디서 돌려도 같은 결과다.

scripts를 import하기 위해 repo 루트의 scripts 디렉토리를 sys.path에 얹는다.
"""
from __future__ import annotations

import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
import ai_harness.check_pr_body as cpb  # noqa: E402

# 설치된 콘솔 스크립트(`ai-harness`)가 사는 venv bin — wired 훅 테스트가 이걸
# PATH에 얹어 "CLI가 설치돼 있는" 실제 환경을 재현한다(미설치 재현은 이걸 뺀다).
_VENV_BIN = str(Path(sys.executable).parent)

# `docs/docs-format/pr-comment.md`는 이 코멘트 게이트를 처음 만든 저장소의
# 폼 파일 경로를 그대로 옮겨온 것이다 — repo별 특화 지점(README가 안내)이라 이
# 저장소엔 아직 없다. 실 배포에서 그 부재는 fail-closed로 이어지는 게 설계대로지만
# (check_pr_body.py 모듈 docstring), 코멘트 게이트·리뷰 근거 검사의 **로직 자체**를
# 검증하는 테스트는 그 부재에 좌우되면 안 된다 — 아래 오토유즈 픽스처로 스텁 폼을
# 물려 격리한다. 폼 파일이 없을 때의 fail-closed 자체는 별도 테스트
# (test_comment_budget_missing_form_is_fail_closed·
# test_review_evidence_missing_form_file_is_fail_closed)가 명시적으로 검증한다.
_STUB_FORM_TEXT = (
    "예산(둘 다 상한): 40줄 · 산문 한 줄 80자·한 문장.\n"
    "헤더에 차수와 대상 커밋을 적는다 — `## 리뷰 종합 — 2차 (8c8f4f7)`.\n"
)


@pytest.fixture(autouse=True)
def _stub_comment_form(monkeypatch, tmp_path):
    form = tmp_path / "pr-comment.md"
    form.write_text(_STUB_FORM_TEXT, encoding="utf-8")
    monkeypatch.setattr(cpb, "_COMMENT_FORM_PATH", form)


@pytest.fixture
def _real_comment_form():
    """`sh -c`로 별도 파이썬 프로세스를 띄우는 `wired_hook` 테스트는 위 monkeypatch가
    안 닿는다(그 프로세스가 실제 경로에서 폼을 다시 읽는다) — 이 픽스처는 실제
    `_COMMENT_FORM_PATH` 자리에 스텁 폼을 잠깐 놓고 테스트가 끝나면 지운다. 이미
    파일이 있으면(이 저장소가 자체 폼을 갖췄으면) 그대로 두고 건드리지 않는다."""
    path = _REPO_ROOT / "src" / "ai_harness" / "docs_format" / "pr-comment.md"
    if path.is_file():
        yield path
        return
    path.write_text(_STUB_FORM_TEXT, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink()


# 통과하는 본문 — 이 fixture가 곧 "예산이 살 만한가"의 실측이다. 예산을 조이다
# 이게 못 통과하게 되면 예산이 틀린 것이다(게이트가 아니라 족쇄).
GOOD_BODY = """\
## 요약

PR 본문에 섹션·분량·용어풀이 게이트를 건다.

## 변경 유형

- [x] ✨ 새 기능

## 관련 이슈

Closes #1

## 변경

- `scripts/check_pr_body.py` — 섹션 4개 필수 + 섹션별 글자예산 + 내부용어 첫등장 풀이 검사
- `.claude/settings.json` — 위 검사기를 PR 생성 전 훅으로 배선(위반 시 리젝)

## 범위 밖

서버측 백스톱(GitHub Actions)은 안 넣음 — 새는 사례 관측되면 그때.

## 검증

`uv run pytest tests/test_check_pr_body.py` → exit 0, 커밋 산출물 기준.

## 확인

- [x] 가독성을 높이는 검수를 진행했다 (PR body 및 comment 대상)
  - [x] 과한 내부 은어 사용 검수했다
  - [x] 비전문가, 제3자도 쉽게 이해할 수 있도록 작성되었는지 검토했다
- [x] 이 변경이 다른 문서를 낡게 하지 않았는지, 작업 중 발견한 기존 stale은 고쳤는지 검토했다 (PR이 영향을 주는 문서들)
  - [x] 바꾼 값·사실을 옮겨 적은 다른 문서도 같이 고쳤는지 확인했다
  - [x] 이 문서를 가리키던 링크·참조가 끊기지 않았는지 확인했다
  - [x] 영향받는 문서의 요약(맨 위 한 줄)이 여전히 맞는지 확인했다
- [x] 필요한 테스트를 추가하거나 갱신했다
- [x] 동작을 깨는 변경(breaking change)이라면 본문에 명시했다
"""


def test_good_body_passes():
    """예산이 실제로 살 만한지 — 통과 본문 하나가 존재해야 게이트다."""
    assert cpb.check_pr_body(GOOD_BODY) == []


def test_missing_section_rejected():
    body = GOOD_BODY.replace("## 검증", "## 딴것")
    violations = cpb.check_pr_body(body)
    assert any("'## 검증' 없음" in v for v in violations)
    assert any("템플릿에 없는 섹션" in v for v in violations)


def test_empty_section_rejected():
    body = "## 요약\n\n요약이다\n\n## 변경\n\n바꿨다\n\n## 범위 밖\n\n## 검증\n\nexit 0\n"
    assert any("'## 범위 밖'이 비었음" in v for v in cpb.check_pr_body(body))


def test_html_comment_only_section_is_empty():
    """템플릿 힌트를 안 지우고 낸 본문 = 빈 섹션. 힌트는 예산도 안 먹는다."""
    body = "## 요약\n\n<!-- 결론 한 줄 -->\n\n## 변경\n\nx\n\n## 범위 밖\n\n없음\n\n## 검증\n\nexit 0\n"
    assert any("'## 요약'이 비었음" in v for v in cpb.check_pr_body(body))


def test_over_budget_section_rejected():
    fat = "가" * (cpb.SECTION_BUDGETS["요약"] + 1)
    body = GOOD_BODY.replace("PR 본문에 섹션·분량·용어풀이 게이트를 건다.", fat)
    violations = cpb.check_pr_body(body)
    assert any("'## 요약'" in v and "예산" in v and "초과" in v for v in violations)


def test_budget_boundary_is_inclusive():
    """정확히 예산만큼은 통과 — 경계에서 한 글자 차이로 리젝되면 안 된다."""
    exact = "가" * cpb.SECTION_BUDGETS["요약"]
    body = GOOD_BODY.replace("PR 본문에 섹션·분량·용어풀이 게이트를 건다.", exact)
    assert not any("'## 요약'" in v for v in cpb.check_pr_body(body))


def test_measure_ignores_layout_whitespace():
    """줄바꿈·들여쓰기는 예산을 먹지 않는다 — 재는 건 내용이지 레이아웃이 아니다."""
    assert cpb.measure("가나\n\n  다  라\n") == cpb.measure("가나 다 라")


# --- 제4조: 내부 용어 풀이 -------------------------------------------------

@pytest.fixture
def with_jargon(monkeypatch):
    """공용 도구의 `JARGON_TERMS` 기본값은 빈 튜플(consumer가 채운다)이라, 은어
    검출 로직을 검증하는 테스트는 테스트-로컬로 목록을 주입한다 — "값이 있으면
    검출, 없으면 통과"라는 계약을 고정한다."""
    monkeypatch.setattr(cpb, "JARGON_TERMS", ("테스트약어", "샘플용어"))


def test_jargon_without_gloss_rejected(with_jargon):
    body = GOOD_BODY.replace("커밋 산출물 기준.", "테스트약어 경로도 확인.")
    assert any("'테스트약어'에 풀이가 없음" in v for v in cpb.check_pr_body(body))


def test_jargon_with_gloss_passes(with_jargon):
    body = GOOD_BODY.replace(
        "커밋 산출물 기준.", "테스트약어(쉬운 말 설명) 확인."
    )
    assert cpb.check_pr_body(body) == []


def test_jargon_in_code_is_ignored(with_jargon):
    """명령어 안의 용어는 산문이 아니다 — 풀이를 요구하지 않는다."""
    body = GOOD_BODY.replace("커밋 산출물 기준.", "`git status`로 테스트약어 확인.")
    assert any("'테스트약어'" in v for v in cpb.check_pr_body(body))
    body_fenced = GOOD_BODY.replace("커밋 산출물 기준.", "`git status --테스트약어`")
    assert cpb.check_pr_body(body_fenced) == []


def test_configured_jargon_rejected_without_gloss(with_jargon):
    """설정된 은어는 풀이 없으면 리젝, 괄호 풀이가 붙으면 통과 — 목록에 실린
    각 용어가 같은 계약을 따른다(목록은 바닥이지 증명 아님)."""
    for term in ("테스트약어", "샘플용어"):
        body = GOOD_BODY.replace("커밋 산출물 기준.", f"{term} 위험.")
        assert any(f"'{term}'에 풀이가 없음" in v for v in cpb.check_pr_body(body)), term
        glossed = GOOD_BODY.replace("커밋 산출물 기준.", f"{term}(쉬운 말) 위험.")
        assert cpb.check_pr_body(glossed) == [], term  # 풀이 붙으면 통과


# --- 한 줄 한 문장(사항별 구조화) -------------------------------------------

def test_multiple_sentences_in_section_rejected():
    """한 불릿에 문장을 몰아넣으면 리젝 — 문장마다 줄바꿈해 구조화하라."""
    body = GOOD_BODY.replace(
        "서버측 백스톱(GitHub Actions)은 안 넣음 — 새는 사례 관측되면 그때.",
        "첫 사항이다. 둘째 사항이 한 줄에 붙었다.",
    )
    assert any("문장이 여럿" in v for v in cpb.check_pr_body(body))


def test_sentence_rule_ignores_code_fence_and_decimals():
    """검증 커맨드·소수는 문장 종결이 아니다 — GOOD_BODY가 그대로 통과한다."""
    assert not any("문장이 여럿" in v for v in cpb.check_pr_body(GOOD_BODY))


# --- 확인 체크리스트 --------------------------------------------------------

@pytest.mark.parametrize("item", cpb.REQUIRED_CHECKS)
def test_unchecked_item_rejected(item):
    """중첩 하위 항목도 각각 강제된다 — 부모만 체크하고 넘어갈 수 없다."""
    body = GOOD_BODY.replace(f"[x] {item}", f"[ ] {item}")
    assert any("체크 안 됨" in v and item in v for v in cpb.check_pr_body(body))


def test_nested_indentation_is_accepted():
    """들여쓴 하위 체크박스도 인식돼야 한다(중첩이 곧 미체크가 되면 안 된다)."""
    checked = cpb.check_checklist(cpb.parse_sections(GOOD_BODY))
    assert checked == []


def test_checklist_excluded_from_budget_total(capsys):
    """`확인` 절은 총계에 안 들어간다 — 저자가 못 줄이는 몫이 예산을 먹으면 안 된다."""
    cpb._report(["dummy"], GOOD_BODY)
    reported = capsys.readouterr().err
    prose_only = sum(
        cpb.measure(cpb.parse_sections(GOOD_BODY).get(n, ""))
        for n in cpb.SECTION_BUDGETS
    )
    assert f"총 {prose_only}자" in reported


def test_missing_checklist_section_rejected():
    body = GOOD_BODY.split("## 확인")[0]
    assert any("'## 확인' 없음" in v for v in cpb.check_pr_body(body))


def test_checklist_is_budget_exempt():
    """체크 문구는 고정이라 저자가 줄일 수 없다 — 예산을 먹이면 안 된다."""
    assert cpb.CHECKLIST_SECTION not in cpb.SECTION_BUDGETS


# --- org 공용 템플릿 통합: 예산 면제 섹션 -----------------------------------
#
# org `.github` 레포의 공용 템플릿이 이미 다른 레포에 `관련 이슈`를 뿌리고
# 있었는데, 게이트는 그걸 "템플릿에 없는 섹션"으로 리젝했다 — 공용 템플릿으로
# 연 PR을 `gh pr merge`가 막는 상태였다(본문을 gh pr view로 끌어와 검사하므로
# 웹에서 연 PR도 걸린다). 아래는 그 통합의 회귀 방지다.

@pytest.mark.parametrize("name", cpb.EXEMPT_SECTIONS)
def test_exempt_section_accepted(name):
    """org 공용 골격 섹션은 '미지 섹션'으로 리젝되면 안 된다."""
    assert not any(
        "템플릿에 없는 섹션" in v and name in v for v in cpb.check_pr_body(GOOD_BODY)
    )


def _drop_section(body: str, name: str) -> str:
    """`## <name>` 헤딩부터 다음 `## ` 헤딩 직전까지를 통째로 지운다."""
    out: list[str] = []
    skipping = False
    for line in body.splitlines(keepends=True):
        if line.startswith("## "):
            skipping = line[3:].strip() == name
        if not skipping:
            out.append(line)
    return "".join(out)


def test_exempt_sections_are_optional():
    """org 템플릿 자신이 '해당 없는 섹션은 지워도 된다'를 계약으로 둔다 —
    존재를 강제하면 그 계약이 깨진다."""
    body = GOOD_BODY
    for name in cpb.EXEMPT_SECTIONS:
        body = _drop_section(body, name)
    for name in cpb.EXEMPT_SECTIONS:
        assert f"## {name}" not in body  # 헬퍼가 실제로 지웠는지부터 확인
    assert cpb.check_pr_body(body) == []


@pytest.mark.parametrize("name", cpb.EXEMPT_SECTIONS)
def test_exempt_section_is_budget_exempt(name):
    """내용이 체크박스·정해진 한 줄이라 저자가 줄일 몫이 아니다 — 예산 밖."""
    assert name not in cpb.SECTION_BUDGETS


def test_every_non_budget_section_has_a_shape():
    """**예산이 없는 섹션은 예외 없이** 형태가 정의돼야 한다.

    예산도 형태도 없는 섹션은 곧 산문 창고다 — 저자는 예산이 넘칠 때마다 넘친
    문장을 거기로 옮기면 되고, 그러면 예산 게이트가 무력화된다.

    실측으로 두 번 당했다:
    1. `_EXEMPT_SHAPE`에 없는 면제 섹션에 장문 산문 → 위반 0건.
    2. `확인` 섹션 뒤에 붙인 산문 → `exit 0` 통과. `확인`은 **필수**라 항상 있고
       GitHub에서 렌더링되므로 `관련 이슈`보다 더 좋은 은신처였다.

    두 번 다 "이 섹션은 형태가 정해져 있다"를 **말로만** 둔 게 원인이다. 그게 이 PR이
    처음 저지른 실수이고, 같은 실수를 한 층 위에서 반복하지 않으려면 이 불변식이
    코드여야 한다(리뷰 지적).
    """
    non_budget = set(cpb.EXEMPT_SECTIONS) | {cpb.CHECKLIST_SECTION}
    assert non_budget == set(cpb._EXEMPT_SHAPE), (
        "예산 없는 섹션과 _EXEMPT_SHAPE가 어긋났다 — 형태 없는 무예산 섹션은 "
        "산문을 무제한 담을 수 있다."
    )


def test_prose_cannot_hide_in_checklist_section():
    """`확인` 절 뒤에 산문을 붙이면 리젝 — 필수 섹션이라 가장 좋은 은신처였다."""
    body = GOOD_BODY + "\n" + "이건 확인 섹션에 붙인 산문이다. " * 12
    assert any("정해진 형태가 아님" in v and "확인" in v
               for v in cpb.check_pr_body(body)), \
        "`확인` 절이 무제한 산문 창고다 — 예산 게이트가 무력화된다"


def test_exempt_section_not_length_budgeted():
    """면제 섹션은 글자수로 재지 않는다 — 대신 형태로 막는다(아래 형태 테스트).

    참조가 여럿이라 길어져도 예산 위반은 안 나와야 한다.
    """
    many = "\n".join(f"Refs #{n}" for n in range(1, 40))
    body = GOOD_BODY.replace("Closes #1", many)
    assert not any("'## 관련 이슈'" in v and "예산" in v for v in cpb.check_pr_body(body))


def test_exempt_section_excluded_from_budget_total(capsys):
    """면제 섹션은 총계에도 안 들어간다 — `확인`과 같은 이유."""
    many = "\n".join(f"Refs #{n}" for n in range(1, 40))
    body = GOOD_BODY.replace("Closes #1", many)
    cpb._report(["dummy"], body)
    reported = capsys.readouterr().err
    prose_only = sum(
        cpb.measure(cpb.parse_sections(body).get(n, "")) for n in cpb.SECTION_BUDGETS
    )
    assert f"총 {prose_only}자" in reported


def test_unknown_section_still_rejected():
    """면제 목록을 열었다고 아무 섹션이나 통과하면 게이트가 아니다."""
    body = GOOD_BODY.replace("## 관련 이슈", "## 아무거나")
    assert any("템플릿에 없는 섹션" in v and "아무거나" in v
               for v in cpb.check_pr_body(body))


# --- 면제 섹션은 형태로 강제한다 ---------------------------------------------
#
# 예산을 안 먹이는 근거가 "정해진 형태라 저자가 줄일 몫이 아니다"이므로, 그 전제를
# 코드가 강제하지 않으면 근거가 거짓이 된다. 실제로 이 게이트를 도입한 PR 자신이
# 넘친 산문을 `관련 이슈`로 옮겨 예산 천장을 우회했다(리뷰 실측). 아래가 그
# 회피구를 닫은 것의 회귀다.

def test_prose_in_exempt_section_rejected():
    """면제 섹션에 산문을 부으면 리젝 — 이게 곧 예산 회피구를 막는 검사다."""
    body = GOOD_BODY.replace("Closes #1", "이 변경은 아주 중요한 이유로 필요했다")
    assert any("정해진 형태가 아님" in v and "관련 이슈" in v
               for v in cpb.check_pr_body(body))


def test_budget_overflow_cannot_hide_in_exempt_section():
    """넘친 산문을 면제 섹션으로 옮겨도 살아나면 안 된다 — 예산의 존재 이유다."""
    overflow = "가" * (cpb.SECTION_BUDGETS["변경"] + 200)
    body = GOOD_BODY.replace("Closes #1", f"Closes #1\n\n{overflow}")
    violations = cpb.check_pr_body(body)
    assert any("정해진 형태가 아님" in v for v in violations), \
        "면제 섹션이 무제한 산문 창고가 됐다 — 예산 게이트가 무력화된다"


@pytest.mark.parametrize("line", [
    "Closes #12", "closes #12", "Fixes #3", "Resolves #7", "Refs #1",
    "#42", "- Refs #1", "Refs owner/repo#12",
    "pollux-o4-labs/ai-harness#21",
    # 아래 3종은 리뷰가 잡은 거짓양성이다 — GitHub이 정상 링크하는 표준 표기인데
    # "한 줄에 참조 하나" 정규식이 리젝했다. 저자는 "이슈 참조만 쓸 수 있다"는 말을
    # 듣는데 자기는 이슈 참조를 썼다 — 진단하지 않는 처방이었다.
    "Closes #1, #2",
    "Closes #1, closes #2",
    "https://github.com/owner/repo/issues/1",
    "없음",
    "N/A",
])
def test_issue_ref_shapes_accepted(line):
    """실제로 쓰이는 참조 형태는 통과해야 한다 — 못 쓰면 게이트가 아니라 족쇄다.

    이 목록은 상상이 아니라 관측이어야 한다(리뷰 지적: 값을 선언해 놓고 그
    값을 안 재고 있었다). 새로 관측되는 표준 표기는 여기 추가한다.
    """
    body = GOOD_BODY.replace("Closes #1", line)
    assert not any("관련 이슈" in v and "정해진 형태" in v
                   for v in cpb.check_pr_body(body)), f"표준 표기 '{line}'이 리젝됐다"


@pytest.mark.parametrize("line", [
    "Closes #1 그리고 이건 덧붙인 설명이다",   # 참조 옆 산문
    "이건 그냥 산문이다",                      # 참조 없음
    "ai-harness#21",                           # 레포명만 — GitHub이 링크 안 함
])
def test_non_ref_lines_rejected(line):
    """참조가 아니거나 참조에 산문을 덧댄 줄은 리젝 — 여기가 산문 창고가 되면 안 된다."""
    body = GOOD_BODY.replace("Closes #1", line)
    assert any("관련 이슈" in v and "정해진 형태" in v
               for v in cpb.check_pr_body(body)), f"'{line}'이 통과했다"


def test_change_type_rejects_prose():
    """`변경 유형`은 체크박스만 — 산문을 받으면 여기도 회피구가 된다."""
    body = GOOD_BODY.replace("- [x] ✨ 새 기능", "새 기능을 넣었고 버그도 고쳤다")
    assert any("정해진 형태가 아님" in v and "변경 유형" in v
               for v in cpb.check_pr_body(body))


@pytest.mark.parametrize("payload,label", [
    ("```\n이건 아주 긴 산문이고 예산을 우회한다\n```", "코드펜스"),
    ("`이건 아주 긴 산문이고 예산을 우회한다`", "인라인코드"),
])
def test_prose_cannot_hide_in_code_markup(payload, label):
    """코드 표기로 감싼 산문도 리젝 — 형태 검사는 코드를 벗기면 안 된다.

    은어·문장 검사는 "코드는 산문이 아니다"라 strip_code로 벗기는 게 맞지만, 형태
    검사에 같은 짓을 하면 감싼 내용이 **사라져서** 섹션이 비어 보이고 통과한다.
    자가 공격으로 실측한 우회구다 — 코드펜스 줄 자체가 이 섹션에 올 수 없는 형태다.
    """
    body = GOOD_BODY.replace("Closes #1", payload)
    assert any("정해진 형태가 아님" in v and "관련 이슈" in v
               for v in cpb.check_pr_body(body)), f"{label}로 산문을 숨길 수 있다"


# --- create/merge 분리: 체크리스트 완료는 머지에서만 -------------------------

def test_create_mode_allows_unchecked_checklist():
    """PR 생성(리뷰 요청) 시점엔 확인 체크리스트가 미체크여도 통과 — 형식만 강제."""
    body = GOOD_BODY.replace("[x]", "[ ]")  # 모든 체크 해제
    assert cpb.check_pr_body(body, require_checklist_complete=False) == []


def test_create_mode_still_enforces_format(with_jargon):
    """create여도 형식(은어 등)은 강제된다 — 체크리스트 완료만 유예."""
    body = GOOD_BODY.replace("[x]", "[ ]").replace("커밋 산출물 기준.", "테스트약어 확인.")
    v = cpb.check_pr_body(body, require_checklist_complete=False)
    assert any("'테스트약어'" in x for x in v)  # 은어는 여전히 잡힘


def test_create_mode_still_requires_checklist_section():
    """create여도 확인 절 자체는 있어야 한다 — 리뷰어가 채울 자리."""
    body = GOOD_BODY.split("## 확인")[0]
    v = cpb.check_pr_body(body, require_checklist_complete=False)
    assert any("'## 확인' 없음" in x for x in v)


def test_merge_mode_requires_all_checked():
    """머지 시점(기본 True)엔 미체크 항목이 있으면 리젝."""
    body = GOOD_BODY.replace("[x] 가독성", "[ ] 가독성")
    assert any("체크 안 됨" in x for x in cpb.check_pr_body(body))  # 기본=완료요구


def test_checkbox_is_self_report_not_evidence(with_jargon):
    """체크박스가 강제하는 것은 글자 'x' 하나뿐임을 고정한다(자기보고 불신).

    이 테스트가 통과한다는 사실 자체가 체크박스의 한계다 — 본문이 서사·은어
    범벅이어도 체크 한 글자로 이 항목은 통과한다. 실물을 재는 것은 섹션·예산·
    풀이 검사이고, 이 항목은 리뷰어에게 넘기는 자기신고에 지나지 않는다.
    """
    lying = GOOD_BODY.replace(
        "PR 본문에 섹션·분량·용어풀이 게이트를 건다.",
        "배경지식 없는 사람은 절대 못 읽는 문장이다.",
    )
    assert cpb.check_checklist(cpb.parse_sections(lying)) == []
    # 실물을 재는 검사(예산·은어)는 여전히 살아 있다 — 체크박스가 그걸 못 끈다.
    assert cpb.check_jargon("## 요약\n\n테스트약어 갱신\n") != []


# --- gh 명령에서 본문 추출 --------------------------------------------------

@pytest.mark.parametrize("cmd", [
    'gh pr create --title t --body-file {p}',
    'gh pr create --title t --body-file={p}',
    'gh pr create -F {p}',
    'cd /repo && gh pr create --body-file {p} --base middle-merge',
    '/usr/bin/gh pr create --body-file {p}',
])
def test_extract_body_from_body_file(tmp_path, cmd):
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    body, reason = cpb.extract_body_from_command(cmd.format(p=p))
    assert reason is None
    assert body == GOOD_BODY


def test_extract_body_inline():
    body, reason = cpb.extract_body_from_command('gh pr create --body "짧은 본문"')
    assert (body, reason) == ("짧은 본문", None)
    body, reason = cpb.extract_body_from_command('gh pr create --body=짧은본문')
    assert (body, reason) == ("짧은본문", None)


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh issue create --body x",   # pr create 아님
    "gh pr view 12",
    "echo 'gh pr create' > note.txt",  # 인접 3토큰이 아님
])
def test_non_target_commands_are_not_inspected(cmd):
    """검사 대상이 아니면 (None, None) — 훅이 통과시켜야 한다."""
    assert cpb.extract_body_from_command(cmd) == (None, None)


def test_uninspectable_call_is_fail_closed():
    """본문을 못 들여다보는 호출은 리젝 사유가 붙는다(우회 차단)."""
    body, reason = cpb.extract_body_from_command("gh pr create --fill")
    assert body is None and reason is not None


def test_missing_body_file_is_fail_closed(tmp_path):
    body, reason = cpb.extract_body_from_command(
        f"gh pr create --body-file {tmp_path / 'nope.md'}"
    )
    assert body is None and "경로 없음" in reason


@pytest.mark.parametrize("raw", ["$SC/body.md", "~/body.md", "`pwd`/body.md", "b*.md"])
def test_shell_expansion_in_path_says_so(raw):
    """쉘 확장은 훅이 못 푼다 — "경로 없음"으로 뭉뚱그리면 오탐이 된다.

    회귀: `--body-file $SC/body.md`가 본문이 멀쩡한데도 "경로 없음"으로 리젝됐다.
    훅은 확장 **전** 명령 문자열을 받으므로 `$VAR`을 영영 풀 수 없다. 막는 것
    자체는 맞으나(fail-closed), 이유를 틀리게 말하면 저자가 게이트를 지운다.
    """
    body, reason = cpb.extract_body_from_command(f"gh pr create --body-file {raw}")
    assert body is None
    assert "쉘 확장" in reason and "리터럴" in reason


# --- 훅 exit 코드 -----------------------------------------------------------

def _run_hook(monkeypatch, command: str) -> int:
    payload = json.dumps({"tool_input": {"command": command}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return cpb.run_hook()


def test_hook_allows_unrelated_command(monkeypatch):
    assert _run_hook(monkeypatch, "git status") == 0


def test_hook_allows_good_body(monkeypatch, tmp_path):
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(monkeypatch, f"gh pr create --body-file {p}") == 0


def test_hook_blocks_bad_body(monkeypatch, tmp_path, capsys):
    p = tmp_path / "body.md"
    p.write_text("## 요약\n\n서사가 길다\n", encoding="utf-8")
    assert _run_hook(monkeypatch, f"gh pr create --body-file {p}") == 2
    assert "리젝" in capsys.readouterr().err


def test_hook_blocks_fill(monkeypatch):
    assert _run_hook(monkeypatch, "gh pr create --fill") == 2


def test_hook_broken_payload_is_nonblocking(monkeypatch, capsys):
    """훅 자체 고장으로 작업을 막지는 않는다 — 리젝(2)이 아니라 오류(1)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cpb.run_hook() == 1


# --- gh pr merge 게이트 ------------------------------------------------------
#
# "머지는 사용자 몫 — 감독·구현자는 머지하지 않는다"를 처음 기계로 강제하는 절.
# 본문은 명령 인자가 아니라 `gh pr view --json body,comments,headRefOid` 능동
# 조회로 얻으므로, 실 gh CLI·네트워크·인증 없이 테스트하려면 subprocess.run 또는
# cpb._fetch_pr_body를 스텁한다.

# `_fetch_pr_body`는 (body, reason)이 아니라 (data, reason)을 반환한다 — data는
# body·comments·headRefOid를 담은 dict다(`--merge-check`·merge 훅 백스톱이
# 체크리스트뿐 아니라 리뷰 종합 코멘트·현재 head SHA도 봐야 해서 조회를
# 확장했다). 기본 comments/head_sha는 신선한 리뷰 종합 코멘트 1개로 채운다 —
# 그 검사 자체(존재·신선도)를 노리는 테스트는 comments/head_sha를 직접 넘긴다.
_DEFAULT_HEAD_SHA = "8c8f4f7"


def _stub_fetch(monkeypatch, *, body: str | None = None, reason: str | None = None,
                 comments: list[dict] | None = None, head_sha: str = _DEFAULT_HEAD_SHA):
    if body is None:
        data = None
    else:
        if comments is None:
            comments = [{"body": f"## 리뷰 종합 — 1차 ({head_sha})\n\n근거."}]
        data = {"body": body, "comments": comments, "headRefOid": head_sha}
    monkeypatch.setattr(cpb, "_fetch_pr_body", lambda identifier: (data, reason))


@pytest.mark.parametrize("argv,expected", [
    (["gh", "pr", "merge", "42"], "42"),
    (["gh", "pr", "merge"], None),  # 생략 — 현재 브랜치를 gh가 추론
    (["gh", "pr", "merge", "--squash", "--delete-branch"], None),
    (["gh", "pr", "merge", "--subject", "메시지", "42"], "42"),
    (["gh", "pr", "merge", "--subject", "메시지"], None),
    (["gh", "pr", "merge", "--subject=메시지", "42"], "42"),
])
def test_merge_target_extraction(argv, expected):
    """PR 번호뿐 아니라, --subject/--body 같은 값-소비 플래그의 값을 식별자로
    오인하지 않아야 한다(안 그러면 정상 머지가 오탐 리젝된다)."""
    assert cpb._merge_target(argv) == expected


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh pr create --fill",
    "gh pr view 42",          # merge 아님 — 오탐 배제
    "gh issue merge 42",      # gh 아님(다른 서브커맨드 조합)
])
def test_extract_body_from_merge_non_target_commands(cmd):
    """gh pr merge가 아니면 (None, None) — 훅이 통과시켜야 한다."""
    assert cpb.extract_body_from_merge_command(cmd) == (None, None)


def test_extract_body_from_merge_uses_fetch(monkeypatch):
    _stub_fetch(monkeypatch, body=GOOD_BODY)
    assert cpb.extract_body_from_merge_command("gh pr merge 42") == (GOOD_BODY, None)


def test_extract_body_from_merge_passes_identifier_to_fetch(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_fetch(identifier):
        captured["id"] = identifier
        return {"body": GOOD_BODY, "comments": [], "headRefOid": "x"}, None

    monkeypatch.setattr(cpb, "_fetch_pr_body", fake_fetch)
    cpb.extract_body_from_merge_command("gh pr merge 42 --squash")
    assert captured["id"] == "42"


def test_extract_body_from_merge_omitted_identifier_passes_none(monkeypatch):
    """PR 번호 생략(현재 브랜치 추론) — gh pr view에 식별자 없이 넘어가야 한다."""
    captured: dict[str, str | None] = {}

    def fake_fetch(identifier):
        captured["id"] = identifier
        return {"body": GOOD_BODY, "comments": [], "headRefOid": "x"}, None

    monkeypatch.setattr(cpb, "_fetch_pr_body", fake_fetch)
    cpb.extract_body_from_merge_command("gh pr merge --squash")
    assert captured["id"] is None


def test_extract_body_from_merge_fetch_failure_is_fail_closed(monkeypatch):
    _stub_fetch(monkeypatch, reason="gh pr view 실패 — 본문을 못 들여다봄(no pull requests found)")
    body, reason = cpb.extract_body_from_merge_command("gh pr merge 999")
    assert body is None
    assert "못 들여다봄" in reason


def test_fetch_pr_body_success(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=json.dumps({"body": GOOD_BODY, "comments": [], "headRefOid": "abc1234"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    data, reason = cpb._fetch_pr_body("42")
    assert reason is None
    assert data == {"body": GOOD_BODY, "comments": [], "headRefOid": "abc1234"}
    assert calls["cmd"] == ["gh", "pr", "view", "42", "--json", "body,comments,headRefOid"]


def test_fetch_pr_body_no_identifier_omits_arg(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"body": "x", "comments": [], "headRefOid": "y"}), stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    cpb._fetch_pr_body(None)
    assert calls["cmd"] == ["gh", "pr", "view", "--json", "body,comments,headRefOid"]


def test_fetch_pr_body_gh_failure_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no pull requests found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    data, reason = cpb._fetch_pr_body("999")
    assert data is None
    assert "못 들여다봄" in reason


def test_fetch_pr_body_bad_json_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    data, reason = cpb._fetch_pr_body("42")
    assert data is None and reason is not None


def test_fetch_pr_body_empty_body_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"body": ""}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    data, reason = cpb._fetch_pr_body("42")
    assert data is None and reason is not None


def test_fetch_pr_body_gh_binary_missing_is_fail_closed(monkeypatch):
    """gh 자체가 없어도(OSError) 크래시 대신 fail-closed 리젝 사유를 낸다."""
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    data, reason = cpb._fetch_pr_body("42")
    assert data is None and reason is not None


# --- 훅 exit 코드: gh pr merge ------------------------------------------------

def test_hook_blocks_merge_with_bad_body(monkeypatch, capsys):
    _stub_fetch(monkeypatch, body="## 요약\n\n서사\n")
    assert _run_hook(monkeypatch, "gh pr merge 42") == 2
    assert "리젝" in capsys.readouterr().err


def test_hook_allows_merge_with_good_body(monkeypatch):
    _stub_fetch(monkeypatch, body=GOOD_BODY)
    assert _run_hook(monkeypatch, "gh pr merge 42") == 0


def test_hook_blocks_merge_when_body_uninspectable(monkeypatch):
    _stub_fetch(monkeypatch, reason="gh pr view 실패 — 본문을 못 들여다봄(인증 안 됨)")
    assert _run_hook(monkeypatch, "gh pr merge 42") == 2


def test_hook_does_not_call_merge_fetch_for_pr_create(monkeypatch, tmp_path):
    """gh pr create는 create 경로로만 처리된다 — merge용 조회가 불릴 필요 없다."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    calls: list[str | None] = []
    monkeypatch.setattr(
        cpb, "_fetch_pr_body",
        lambda identifier: (calls.append(identifier), (None, "should not be called"))[1],
    )
    assert _run_hook(monkeypatch, f"gh pr create --body-file {p}") == 0
    assert calls == []


def test_hook_allows_gh_pr_view_unrelated(monkeypatch):
    """gh pr view는 merge도 create도 아니다 — 오탐 없이 통과."""
    assert _run_hook(monkeypatch, "gh pr view 42") == 0


# --- settings.json 배선(쉘 래퍼) --------------------------------------------
#
# 유닛테스트가 아니라 **커밋되는 배선 그 자체**를 돌린다 — 도입 중 실제로 문 것은
# 검사기가 아니라 settings.json의 쉘 한 줄이었다(파일 부재 시 python이 exit 2로
# 죽어 저장소의 모든 Bash가 막혔다). 그 층에 테스트가 없으면 같은 게 또 문다.

def _hook_command() -> str:
    """커밋된 .claude/settings.json에서 PreToolUse 훅 명령을 그대로 꺼낸다."""
    settings = json.loads(
        (_REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    matchers = settings["hooks"]["PreToolUse"]
    commands = [
        h["command"]
        for m in matchers if m.get("matcher") == "Bash"
        for h in m["hooks"] if "check-pr" in h.get("command", "")
    ]
    assert len(commands) == 1, f"Bash용 check-pr 훅이 1개가 아님: {commands}"
    return commands[0]


def _run_wired_hook(command: str, project_dir: Path, *, cli_on_path: bool = True) -> int:
    """훅 래퍼를 실제 sh로 실행하고 종료코드를 돌려준다.

    cli_on_path=False 는 `ai-harness` 미설치를 재현한다(fail-open 검증용)."""
    path = f"{_VENV_BIN}:/usr/bin:/bin" if cli_on_path else "/usr/bin:/bin"
    return subprocess.run(
        ["sh", "-c", _hook_command()],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True,
        env={"PATH": path, "CLAUDE_PROJECT_DIR": str(project_dir)},
    ).returncode


def test_wired_hook_blocks_bad_body(tmp_path):
    p = tmp_path / "body.md"
    p.write_text("## 요약\n\n서사\n", encoding="utf-8")
    assert _run_wired_hook(f"gh pr create --body-file {p}", _REPO_ROOT) == 2


def test_wired_hook_allows_good_body(tmp_path):
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_wired_hook(f"gh pr create --body-file {p}", _REPO_ROOT) == 0


def test_wired_hook_allows_unrelated_command():
    assert _run_wired_hook("git status", _REPO_ROOT) == 0


def test_wired_hook_does_not_lock_repo_when_checker_absent(tmp_path):
    """검사기가 없으면 게이트는 꺼지되 저장소를 잠그지는 않는다.

    회귀: 초기 배선은 `python3 <없는파일>`이 exit 2로 죽었고, 훅 규약에서 2는
    '차단'이라 저장소의 모든 Bash 명령이 막혔다(게이트가 자기 자신을 잠금).
    지금은 `command -v ai-harness`로 미설치를 감지해 건너뛴다 — CLI 부재는
    운영자가 볼 수 있는 문제이므로, 전 명령을 막는 것보다 조용히 꺼지는 편이
    덜 해롭다(cli_on_path=False로 미설치를 재현).
    """
    assert _run_wired_hook("git status", tmp_path, cli_on_path=False) == 0


def test_wired_hook_does_not_swallow_rejection(tmp_path):
    """래퍼가 리젝을 통과로 바꾸지 않는다.

    회귀: `test -f X && python3 X --hook || exit 0`은 쉘 우선순위상 python이
    2로 죽어도 `|| exit 0`이 받아 **모든 리젝이 통과**가 된다. 부재 처리를
    넣을 때 이 함정을 다시 밟기 쉬우므로 회귀로 고정한다.
    """
    p = tmp_path / "body.md"
    p.write_text("## 요약\n\n서사\n", encoding="utf-8")
    assert _run_wired_hook(f"gh pr create --body-file {p}", _REPO_ROOT) != 0


# --- gh pr merge 배선(쉘 래퍼) — 실 gh 없이 가짜 gh로 배선 자체를 검증 -------
#
# .claude/settings.json은 이미 모든 Bash 호출을 check_pr_body.py --hook로
# 보낸다 — gh pr merge 처리를 추가해도 settings.json 자체는 안 바뀐다. 그래도
# "새 코드 경로가 그 기존 배선을 통해 실제로 도달 가능한가"는 별도로 증명해야
# 한다 — 이 서브프로세스는 monkeypatch가 안 닿으므로 PATH에 가짜 gh를 심는다.

def _make_fake_gh(tmp_path: Path, response_body: str, *,
                   comments: list[dict] | None = None, head_sha: str = "8c8f4f7") -> Path:
    """`gh pr view ... --json body,comments,headRefOid` 호출에 고정 JSON을
    돌려주는 가짜 gh. 인자를 안 가리고 항상 같은 응답을 낸다 — 배선 자체
    검증용이라 이걸로 충분. comments 생략 시 신선한 리뷰 종합 코멘트 1개를
    기본으로 채운다(그 존재·신선도 자체를 노리는 테스트는 comments를 직접
    넘긴다)."""
    if comments is None:
        comments = [{"body": f"## 리뷰 종합 — 1차 ({head_sha})\n\n근거."}]
    payload = tmp_path / "gh_response.json"
    payload.write_text(
        json.dumps({"body": response_body, "comments": comments, "headRefOid": head_sha}),
        encoding="utf-8",
    )
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(f'#!/usr/bin/env bash\ncat "{payload}"\n', encoding="utf-8")
    fake_gh.chmod(0o755)
    return tmp_path


def _run_wired_hook_with_fake_gh(command: str, fake_gh_dir: Path) -> int:
    return subprocess.run(
        ["sh", "-c", _hook_command()],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True,
        env={"PATH": f"{fake_gh_dir}:{_VENV_BIN}:/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(_REPO_ROOT)},
    ).returncode


def test_wired_hook_blocks_merge_with_bad_body(tmp_path):
    fake_gh_dir = _make_fake_gh(tmp_path, "## 요약\n\n서사\n")
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 2


def test_wired_hook_allows_merge_with_good_body(tmp_path, _real_comment_form):
    fake_gh_dir = _make_fake_gh(tmp_path, GOOD_BODY)
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 0


def test_wired_hook_blocks_merge_when_review_evidence_missing(tmp_path, _real_comment_form):
    """체크리스트가 전량 체크돼도 리뷰 종합 코멘트가 없으면 리젝(백스톱).

    `_real_comment_form` 없이는 폼 파일 부재로 인한 fail-closed와 구분이 안 돼
    "위반 없어서 통과할 뻔한 것"과 "의도한 위반"이 우연히 같은 exit 2로 섞인다
    (홀로우 그린, 리뷰 지적) — 폼을 실제로 놓아 이 테스트가 노리는 위반
    (코멘트 없음)이 실제 사유가 되게 한다."""
    fake_gh_dir = _make_fake_gh(tmp_path, GOOD_BODY, comments=[])
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 2


def test_wired_hook_blocks_merge_when_review_evidence_stale(tmp_path, _real_comment_form):
    """최신 코멘트의 SHA가 현재 head와 다르면 리젝 — 옛 코멘트로 영구통과 방지."""
    fake_gh_dir = _make_fake_gh(
        tmp_path, GOOD_BODY,
        comments=[{"body": "## 리뷰 종합 — 1차 (0000000)\n\n낡은 근거."}],
        head_sha="1111111",
    )
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 2


# --- 리뷰 근거 존재·신선도(check_review_evidence) -----------------------------
#
# "근거 없는 체크 금지"를 처음 기계로 태우는 검사 — 체크리스트
# 완료만으론 통과 못 하게 하는 축이다. 헤더 접두어는 pr-comment.md의 예시
# 문구에서 파싱한다(load_review_header_prefix) — 여기 하드코딩하지 않는다.

def test_review_evidence_passes_with_fresh_comment():
    comments = [{"body": "## 리뷰 종합 — 1차 (abc1234)\n\n근거."}]
    assert cpb.check_review_evidence(comments, "abc1234def") == []


def test_review_evidence_rejects_no_matching_comment():
    violations = cpb.check_review_evidence([{"body": "그냥 코멘트."}], "abc1234")
    assert any("리뷰 종합 코멘트 없음" in v for v in violations)


def test_review_evidence_rejects_stale_sha():
    """최신 코멘트의 SHA가 현재 head와 다르면 리젝 — 옛 코멘트로 영구통과 방지."""
    comments = [{"body": "## 리뷰 종합 — 1차 (abc1234)\n\n근거."}]
    violations = cpb.check_review_evidence(comments, "9999999")
    assert any("리뷰 근거가 낡음" in v for v in violations)


def test_review_evidence_uses_latest_matching_comment():
    """코멘트가 여럿이면 목록의 마지막(최신) 매치만 본다 — 옛 판정이 최신
    판정을 가리면 안 된다."""
    comments = [
        {"body": "## 리뷰 종합 — 1차 (0000000)\n\n낡은 근거."},
        {"body": "그 사이 무관한 코멘트."},
        {"body": "## 리뷰 종합 — 2차 (abc1234)\n\n최신 근거."},
    ]
    assert cpb.check_review_evidence(comments, "abc1234def") == []


def test_review_evidence_missing_form_file_is_fail_closed(monkeypatch):
    """폼 파일을 못 찾으면 잴 자가 없어서 통과가 아니라 리젝한다(fail-closed)."""
    monkeypatch.setattr(cpb, "_COMMENT_FORM_PATH", Path("/nonexistent/pr-comment.md"))
    violations = cpb.check_review_evidence(
        [{"body": "## 리뷰 종합 — 1차 (abc1234)"}], "abc1234"
    )
    assert violations != []


# --- --merge-check dry-run ---------------------------------------------------
#
# `gh pr merge`를 부르지 않는다 — check_merge_readiness의 3종 판정(체크리스트
# 전량 + 리뷰 종합 코멘트 존재·신선도)을 사람이 미리 돌려보는 CLI 진입점이다.

def test_check_merge_readiness_passes_when_all_conditions_met(monkeypatch):
    _stub_fetch(monkeypatch, body=GOOD_BODY)
    assert cpb.check_merge_readiness("42") == []


def test_check_merge_readiness_rejects_when_review_evidence_missing(monkeypatch):
    _stub_fetch(monkeypatch, body=GOOD_BODY, comments=[])
    violations = cpb.check_merge_readiness("42")
    assert any("리뷰 종합 코멘트 없음" in v for v in violations)


def test_check_merge_readiness_rejects_stale_review_evidence(monkeypatch):
    _stub_fetch(
        monkeypatch, body=GOOD_BODY,
        comments=[{"body": "## 리뷰 종합 — 1차 (deadbee)\n\n근거."}],
        head_sha="1111111",
    )
    violations = cpb.check_merge_readiness("42")
    assert any("리뷰 근거가 낡음" in v for v in violations)


def test_check_merge_readiness_rejects_incomplete_checklist(monkeypatch):
    """리뷰 근거가 신선해도 체크리스트가 전량 체크 안 되면 여전히 리젝."""
    body = GOOD_BODY.replace("[x] 가독성", "[ ] 가독성")
    _stub_fetch(monkeypatch, body=body)
    violations = cpb.check_merge_readiness("42")
    assert any("체크 안 됨" in v for v in violations)


def test_check_merge_readiness_fetch_failure_is_fail_closed(monkeypatch):
    _stub_fetch(monkeypatch, reason="gh pr view 실패 — 본문을 못 들여다봄(인증 안 됨)")
    violations = cpb.check_merge_readiness("999")
    assert any("못 들여다봄" in v for v in violations)


def test_merge_check_cli_pass_prints_ready_message(monkeypatch, capsys):
    _stub_fetch(monkeypatch, body=GOOD_BODY)
    assert cpb.main(["--merge-check", "42"]) == 0
    assert "리뷰 근거 확인됨" in capsys.readouterr().out


def test_merge_check_cli_fail_reports_violations(monkeypatch, capsys):
    _stub_fetch(monkeypatch, body=GOOD_BODY, comments=[])
    assert cpb.main(["--merge-check", "42"]) == 1
    assert "머지 준비 안 됨" in capsys.readouterr().err


# --- gh pr comment 게이트 ----------------------------------------------------
#
# 코멘트는 리뷰 항목별 근거 기록이지 PR 본문이 아니다 — 섹션 골격·체크리스트는
# 적용하지 않는다(감독 최초 지시). 단, 내부 용어 풀이(JARGON_TERMS)는 코멘트도
# PR에 남는 글이라 적용한다(감독 정정 — 체크리스트 은어 항목의 적용범위가
# "PR에 작성된 글"이라 코멘트도 포함된다). 강제 축은 줄수·줄자수·문장구조·은어뿐.

GOOD_COMMENT = """\
- 요약 섹션 근거: 실측 143자, 예산 150자 이내.
- 변경 섹션 근거: 파일 3개 수정, 신규 코드 없음.
- 검증 근거: pytest 그린, exit 0.
"""


def test_comment_good_form_passes():
    """섹션 골격·체크리스트 없이도 통과해야 한다 — 코멘트는 자유 형식이다."""
    assert cpb.check_comment(GOOD_COMMENT) == []


def test_comment_long_line_rejected():
    """80자 초과 코멘트 줄은 리젝된다."""
    line_max = cpb.load_comment_budgets()["line_chars"]
    body = GOOD_COMMENT + f"- {'가' * (line_max + 1)}\n"
    violations = cpb.check_comment(body)
    assert any(f"> {line_max}자" in v for v in violations)


def test_comment_multiple_sentences_rejected():
    """한 줄에 문장 둘(마침표 뒤 문장이 이어짐)이면 리젝 — 한 줄 한 문장."""
    body = GOOD_COMMENT + "- 첫 사항이다. 둘째 사항이 한 줄에 붙었다.\n"
    assert any("문장이 여럿" in v for v in cpb.check_comment(body))


def test_comment_code_fence_line_exempt():
    """펜스 안의 긴 줄·문장 여럿은 면제 — 명령·출력 인용은 쪼개면 깨진다."""
    fenced = "```\n" + ("x" * 90) + "\n첫 문장이다. 둘째 문장.\n```\n"
    assert cpb.check_comment(GOOD_COMMENT + fenced) == []


def test_comment_too_many_lines_rejected():
    """40줄(폼 예산) 초과 코멘트는 총량 위반으로 리젝된다."""
    lines_max = cpb.load_comment_budgets()["max_lines"]
    body = "\n".join(f"- 항목 {i} 확인." for i in range(lines_max + 5))
    violations = cpb.check_comment(body)
    assert any(f"> {lines_max}줄" in v for v in violations)


def test_comment_jargon_without_gloss_rejected(with_jargon):
    """JARGON_TERMS의 용어를 괄호 풀이 없이 쓰면 리젝 — 기존 검사기 재사용."""
    body = GOOD_COMMENT + "- 테스트약어 경로 확인.\n"
    assert any("'테스트약어'에 풀이가 없음" in v for v in cpb.check_comment(body))


def test_comment_jargon_with_gloss_passes():
    """괄호 풀이가 붙으면 통과."""
    body = GOOD_COMMENT + "- 테스트약어(대체 경로) 확인.\n"
    assert cpb.check_comment(body) == []


def test_comment_budget_missing_form_is_fail_closed(monkeypatch):
    """폼 파일을 못 찾으면 잴 자가 없어서 통과가 아니라 리젝한다(fail-closed)."""
    monkeypatch.setattr(cpb, "_COMMENT_FORM_PATH", Path("/nonexistent/pr-comment.md"))
    assert cpb.check_comment(GOOD_COMMENT) != []


@pytest.mark.parametrize("cmd", [
    'gh pr comment 42 --body-file {p}',
    'gh pr comment 42 --body-file={p}',
    'gh pr comment 42 -F {p}',
    'cd /repo && gh pr comment 42 --body-file {p}',
])
def test_extract_body_from_comment_command_file(tmp_path, cmd):
    p = tmp_path / "comment.md"
    p.write_text(GOOD_COMMENT, encoding="utf-8")
    body, reason = cpb.extract_body_from_comment_command(cmd.format(p=p))
    assert reason is None
    assert body == GOOD_COMMENT


def test_extract_body_from_comment_inline():
    body, reason = cpb.extract_body_from_comment_command(
        'gh pr comment 42 --body "짧은 코멘트"'
    )
    assert (body, reason) == ("짧은 코멘트", None)


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh pr create --body x",
    "gh pr merge 42",
    "gh issue comment 42 --body x",
    "gh pr view 42",
])
def test_comment_non_target_commands_are_not_inspected(cmd):
    """검사 대상이 아니면 (None, None) — 훅이 통과시켜야 한다."""
    assert cpb.extract_body_from_comment_command(cmd) == (None, None)


def test_comment_uninspectable_call_is_fail_closed():
    """본문 플래그 없는 호출(에디터 대화형 등)은 리젝 사유가 붙는다."""
    body, reason = cpb.extract_body_from_comment_command("gh pr comment 42")
    assert body is None and reason is not None


def test_hook_allows_good_comment(monkeypatch, tmp_path):
    p = tmp_path / "comment.md"
    p.write_text(GOOD_COMMENT, encoding="utf-8")
    assert _run_hook(monkeypatch, f"gh pr comment 42 --body-file {p}") == 0


def test_hook_blocks_bad_comment(monkeypatch, tmp_path, capsys):
    p = tmp_path / "comment.md"
    p.write_text("가" * 90 + "\n", encoding="utf-8")
    assert _run_hook(monkeypatch, f"gh pr comment 42 --body-file {p}") == 2
    assert "리젝" in capsys.readouterr().err


def test_hook_blocks_comment_without_body(monkeypatch):
    assert _run_hook(monkeypatch, "gh pr comment 42") == 2


# --- 기존 경로(create·merge) 회귀 고정 — comment 추가가 안 건드렸는지 --------

def test_hook_does_not_call_comment_check_for_pr_create(monkeypatch, tmp_path):
    """gh pr create는 create 경로로만 처리된다 — comment 검사기가 안 불린다."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(cpb, "check_comment", lambda body: calls.append(body) or [])
    assert _run_hook(monkeypatch, f"gh pr create --body-file {p}") == 0
    assert calls == []


def test_hook_does_not_call_pr_body_check_for_comment(monkeypatch, tmp_path):
    """gh pr comment는 comment 경로로만 처리된다 — 섹션 게이트가 안 불린다."""
    p = tmp_path / "comment.md"
    p.write_text(GOOD_COMMENT, encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(cpb, "check_pr_body", lambda body, **kw: calls.append(body) or [])
    assert _run_hook(monkeypatch, f"gh pr comment 42 --body-file {p}") == 0
    assert calls == []


def test_wired_hook_allows_good_comment(tmp_path, _real_comment_form):
    p = tmp_path / "comment.md"
    p.write_text(GOOD_COMMENT, encoding="utf-8")
    assert _run_wired_hook(f"gh pr comment 42 --body-file {p}", _REPO_ROOT) == 0


def test_wired_hook_blocks_bad_comment(tmp_path, _real_comment_form):
    """`_real_comment_form` 없이는 폼 파일 부재로 인한 fail-closed와 구분이 안 돼
    "위반 없어서 통과할 뻔한 것"과 "의도한 위반"(80자 초과)이 우연히 같은 exit 2로
    섞인다(홀로우 그린, 리뷰 지적) — 폼을 실제로 놓아 이 테스트가 노리는
    위반이 실제 사유가 되게 한다."""
    p = tmp_path / "comment.md"
    p.write_text("가" * 90 + "\n", encoding="utf-8")
    assert _run_wired_hook(f"gh pr comment 42 --body-file {p}", _REPO_ROOT) == 2


# --- CRITICAL: shlex는 셸 구조를 모른다 — 오탐 매칭 자기진단 ------------------
#
# 실사고: 파이썬 heredoc 안의 주석 한 줄("# gh pr comment preceded by env
# assignment")이 shlex.split 결과에서 "gh","pr","comment"가 인접해 gh 호출로
# 오인됐고, 실제 --body가 없어 exit 2로 리젝됐다(gh를 호출하지도 않은 명령이
# 막힘). **근본 해결은 불가능하다** — shlex는 진짜 셸 파서가 아니라 주석·
# heredoc·문자열 안 평문을 구별 못 한다. 대신: (1) --body/--body-file 탐색을
# 매칭된 gh 호출과 같은 셸 세그먼트로 좁히고(국소성), (2) 리젝 사유에 어떤
# 토큰을 gh 호출로 인식했는지 노출해 오탐 자기진단 비용을 줄인다.

def test_comment_false_positive_in_prose_is_diagnosable():
    """오탐(주석 속 평문)은 여전히 리젝되지만(근본 해결 불가), 사유에 매칭
    위치가 드러나야 한다 — 사람이 즉시 오탐임을 판별할 수 있게."""
    command = "echo start\n# gh pr comment preceded by env assignment\necho end"
    body, reason = cpb.extract_body_from_comment_command(command)
    assert body is None
    assert reason is not None
    argv = shlex.split(command)
    gh_idx = argv.index("gh")
    assert str(gh_idx) in reason
    assert repr(argv[gh_idx:gh_idx + 3]) in reason


def test_comment_body_flag_before_match_is_not_used(tmp_path):
    """국소성: 매칭보다 앞선(무관한 다른 명령의) --body-file은 이 gh 호출
    소속으로 오인해선 안 된다 — 회귀: 예전엔 argv 전체를 인덱스 0부터 스캔해
    이런 파일 내용을 엉뚱하게 본문으로 썼다."""
    leftover = tmp_path / "leftover.md"
    leftover.write_text("- 무관한 내용입니다.\n", encoding="utf-8")
    command = f"cat --body-file {leftover} && gh pr comment 42"
    body, reason = cpb.extract_body_from_comment_command(command)
    assert body is None  # leftover.md 내용을 본문으로 쓰면 안 된다
    assert reason is not None  # 대신 '본문 없음'으로 fail-closed


def test_create_body_flag_after_next_segment_is_not_used(tmp_path):
    """국소성: 매칭된 gh 호출 뒤 `&&`로 이어진 무관한 다음 명령의 --body도
    이 호출 소속이 아니다."""
    command = 'gh pr create 2>/dev/null && echo unrelated --body "엉뚱한 본문"'
    body, reason = cpb.extract_body_from_command(command)
    assert body is None
    assert reason is not None


# --- HIGH-1: 미닫힘 코드펜스가 EOF까지 검사를 면제하면 안 된다 ---------------

def test_comment_unterminated_fence_is_not_exempt():
    """미닫힘 코드펜스는 EOF까지 검사를 면제해선 안 된다(뮤테이션 방어 회귀) —
    닫아도 안 닫아도 결과가 같으면 우회 통로가 된다. 재현: 이 게이트가 막으려던
    긴 산문 사고와 같은 모양(긴 줄 + 문장 여럿)을 펜스로 감싸면 통과해선 안 된다."""
    body = "- 정상 근거 줄입니다.\n```\n" + (("x" * 200) + ". 두번째 문장.\n") * 5
    violations = cpb.check_comment(body)
    assert violations != []
    assert any("닫" in v for v in violations)  # 미닫힘 자체가 위반으로 잡혀야 한다
    # 미닫힘 구간은 면제되지 않으므로 안의 문장·줄자수 위반도 같이 잡혀야 한다.
    assert any("문장이 여럿" in v for v in violations)
    assert any("자 >" in v for v in violations)


def test_comment_terminated_fence_pair_before_unterminated_one_still_exempt():
    """닫힌 펜스 쌍은 그대로 면제되고, 그 뒤에 새로 열려 안 닫힌 펜스만 위반이
    잡혀야 한다 — 미닫힘 판정이 이전의 정상 닫힌 블록까지 덮어쓰면 안 된다."""
    closed = "```\n" + ("y" * 90) + "\n```\n"  # GOOD_COMMENT 뒤 4~6번째 줄, 닫힌 쌍
    unterminated = "```\n" + (("x" * 200) + ". 두번째 문장.\n")  # 7~8번째 줄
    body = GOOD_COMMENT + closed + unterminated
    violations = cpb.check_comment(body)
    assert len(violations) == 3  # 미닫힘 1건 + 8번째 줄의 문장·길이 위반 2건
    assert any("닫" in v for v in violations)
    assert any("문장이 여럿" in v for v in violations)
    assert any("자 >" in v for v in violations)
    # 닫힌 쌍 안(5번째 줄, y*90)은 그대로 면제라 그 줄을 지목하는 위반이 없어야 한다.
    assert not any(v.startswith("코멘트 5번째 줄") for v in violations)


# --- HIGH-2: 전역 플래그(--repo/-R)가 gh 바로 뒤에 오면 놓친다 ----------------

def test_comment_recognizes_global_repo_flag():
    """`gh --repo o/r pr comment ...`처럼 전역 플래그가 subcommand 앞에 와도
    인식해야 한다 — 인접 3토큰 고정 매칭은 이걸 놓쳐 조용히 샌다(무검사 통과)."""
    body, reason = cpb.extract_body_from_comment_command(
        'gh --repo owner/repo pr comment 42 --body "짧은 코멘트"'
    )
    assert (body, reason) == ("짧은 코멘트", None)


def test_create_recognizes_global_repo_flag_short_form(tmp_path):
    """`-R` 단축형도 같은 함수라 create도 같이 고쳐진다(선재 결함)."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    body, reason = cpb.extract_body_from_command(f"gh -R o/r pr create --body-file {p}")
    assert reason is None
    assert body == GOOD_BODY


def test_merge_recognizes_global_repo_flag(monkeypatch):
    """merge도 같은 매칭 함수를 쓰므로 같이 고쳐진다(선재 결함)."""
    captured: dict[str, str | None] = {}

    def fake_fetch(identifier):
        captured["id"] = identifier
        return {"body": GOOD_BODY, "comments": [], "headRefOid": "x"}, None

    monkeypatch.setattr(cpb, "_fetch_pr_body", fake_fetch)
    body, reason = cpb.extract_body_from_merge_command("gh --repo o/r pr merge 42")
    assert (body, reason) == (GOOD_BODY, None)
    assert captured["id"] == "42"


# --- gh pr create 제목 게이트(S5): conventional-commit -----------------------
#
# 제목은 create 전용 축이다 — merge는 이미 만들어진 PR을 가리킬 뿐 제목을 새로
# 짓지 않고, comment는 애초에 제목이 없다. 제목 플래그(--title/-t)가 없는 create
# 호출은 리젝하지 않는다(fail-open) — 이 게이트가 강제하는 건 "제목이 있다면
# 형식이 맞아야 한다"이지 "제목이 항상 있어야 한다"가 아니다(그 부재는 이미
# body 부재 경로가 fail-closed로 잡는다).

@pytest.mark.parametrize("title", [
    "feat: PR 제목 게이트 추가",
    "fix(gate): 콜론 뒤 공백 검사",
    "docs: README 갱신",
    "chore: 의존성 정리",
    "refactor(check_pr_body): 함수 분리",
    "test: 회귀 테스트 추가",
    "perf: 정규식 캐시",
    "build: 패키징 설정",
    "ci: 워크플로 갱신",
    "style: 공백 정리",
    "revert: 이전 커밋 되돌림",
])
def test_valid_title_passes(title):
    """허용 타입 11종 각각이 통과해야 한다 — 목록이 실측이지 상상이 아니다."""
    assert cpb.check_pr_title(title) == []


def test_unknown_type_rejected():
    violations = cpb.check_pr_title("feature: 오타난 타입")
    assert any("타입 'feature' 미지" in v for v in violations)


def test_title_missing_colon_rejected():
    violations = cpb.check_pr_title("이건 콜론이 없는 제목이다")
    assert any("형식 위반" in v for v in violations)


def test_title_missing_space_after_colon_rejected():
    """콜론 뒤 공백이 없으면 형식 위반 — `type:subject`는 관례를 안 따른다."""
    assert any("형식 위반" in v for v in cpb.check_pr_title("fix:공백없음"))


def test_title_with_scope_unknown_type_still_rejected():
    """스코프가 붙어도 타입 검사는 그대로 적용된다."""
    violations = cpb.check_pr_title("feature(gate): 스코프가 있어도 타입은 검사한다")
    assert any("타입 'feature' 미지" in v for v in violations)


def test_title_uppercase_type_reported_as_unknown():
    """대문자 타입은 '형식 위반'이 아니라 '타입 미지'로 알려줘야 저자가 뭘
    고칠지 안다(오타 진단성) — "Fix"는 콜론·공백 형식은 맞으므로 형식 문제가
    아니라 타입 문제다."""
    violations = cpb.check_pr_title("Fix: 대문자 타입")
    assert any("타입 'Fix' 미지" in v for v in violations)


def test_extract_title_finds_long_flag():
    title, reason = cpb.extract_title_from_command(
        'gh pr create --title "feat: 새 기능" --body-file f'
    )
    assert (title, reason) == ("feat: 새 기능", None)


def test_extract_title_finds_short_flag():
    title, reason = cpb.extract_title_from_command(
        'gh pr create -t "fix: 버그" --body-file f'
    )
    assert (title, reason) == ("fix: 버그", None)


def test_extract_title_finds_equals_form():
    title, reason = cpb.extract_title_from_command(
        "gh pr create --title=fix:버그 --body-file f"
    )
    assert (title, reason) == ("fix:버그", None)


def test_extract_title_finds_short_flag_equals_form():
    """`-t=VALUE`도 파싱한다(회귀 — 리뷰 SHOULD-FIX#1) — 이전엔 못 읽어 제목이
    실재하는데도 fail-open으로 새는 우회구였다."""
    title, reason = cpb.extract_title_from_command(
        "gh pr create -t=fix:버그 --body-file f"
    )
    assert (title, reason) == ("fix:버그", None)


def test_extract_title_finds_short_flag_attached_form():
    """`-tVALUE`(공백 없는 붙임꼴)도 파싱한다(회귀 — 리뷰 SHOULD-FIX#1)."""
    title, reason = cpb.extract_title_from_command(
        'gh pr create -t"fix: 버그" --body-file f'
    )
    assert (title, reason) == ("fix: 버그", None)


def test_extract_title_absent_is_not_rejected():
    """제목 플래그가 없는 create 호출은 (None, None) — fail-open(설계 결정,
    모듈 docstring 참조)."""
    assert cpb.extract_title_from_command("gh pr create --body-file f") == (None, None)


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh pr merge 42 --subject t",
    "gh pr comment 42 --body x",
    "gh issue create --title t",
])
def test_extract_title_non_create_commands_not_inspected(cmd):
    """create가 아니면 (None, None) — 훅이 통과시켜야 한다(create 아닌 호출
    무영향)."""
    assert cpb.extract_title_from_command(cmd) == (None, None)


def test_hook_blocks_bad_title(monkeypatch, tmp_path, capsys):
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(
        monkeypatch, f'gh pr create --title "오타타입: 제목" --body-file {p}'
    ) == 2
    assert "PR 제목 리젝" in capsys.readouterr().err


def test_hook_allows_good_title(monkeypatch, tmp_path):
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(
        monkeypatch, f'gh pr create --title "feat: 제목 게이트" --body-file {p}'
    ) == 0


def test_hook_allows_good_title_via_short_flag_attached_form(monkeypatch, tmp_path):
    """`-tVALUE`(공백 없는 붙임꼴)로 넘긴 유효 제목도 훅 경로에서 통과해야
    한다(리뷰 SHOULD-FIX#1)."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(
        monkeypatch, f'gh pr create -t"feat: 붙임꼴 제목" --body-file {p}'
    ) == 0


def test_hook_blocks_bad_title_via_short_flag_attached_form(monkeypatch, tmp_path, capsys):
    """회귀: `-tVALUE` 붙임꼴을 못 읽으면 제목이 실재하는데도 fail-open으로
    새던 우회구였다 — 이제 미지 타입이 잡힌다(리뷰 SHOULD-FIX#1)."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(
        monkeypatch, f'gh pr create -t"bogus: 제목" --body-file {p}'
    ) == 2
    assert "타입 'bogus' 미지" in capsys.readouterr().err


def test_hook_allows_missing_title(monkeypatch, tmp_path):
    """제목 플래그가 없어도 create 자체가 리젝되진 않는다(fail-open) — 기존
    create 테스트 다수가 --title 없이 돈다(회귀 방지)."""
    p = tmp_path / "body.md"
    p.write_text(GOOD_BODY, encoding="utf-8")
    assert _run_hook(monkeypatch, f"gh pr create --body-file {p}") == 0


def test_hook_does_not_check_title_for_merge(monkeypatch):
    """merge에는 제목 개념이 없다 — 제목 검사기가 안 불린다."""
    _stub_fetch(monkeypatch, body=GOOD_BODY)
    calls: list[str] = []
    monkeypatch.setattr(cpb, "check_pr_title", lambda title: calls.append(title) or [])
    assert _run_hook(monkeypatch, "gh pr merge 42") == 0
    assert calls == []


def test_hook_does_not_check_title_for_comment(monkeypatch, tmp_path):
    """comment에도 제목 개념이 없다 — 제목 검사기가 안 불린다."""
    p = tmp_path / "comment.md"
    p.write_text(GOOD_COMMENT, encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(cpb, "check_pr_title", lambda title: calls.append(title) or [])
    assert _run_hook(monkeypatch, f"gh pr comment 42 --body-file {p}") == 0
    assert calls == []


# --- 템플릿 ↔ 스크립트 정합 --------------------------------------------------
#
# 템플릿 문구와 REQUIRED_CHECKS가 한 글자라도 어긋나면 그 레포의 **모든 PR이 머지
# 불가**가 된다(check_checklist가 정확일치를 요구하므로). 그런데 템플릿 파일을 읽는
# 테스트가 하나도 없으면, 어느 쪽이 드리프트해도 스위트는 초록이다 — 이 게이트가
# 고치려는 버그와 정확히 같은 부류다(리뷰 실측).
#
# 대조 대상이 **파일**이므로 자기참조가 아니다: 상수에서 케이스를 파생하되 상수와
# 파일을 맞대므로, 한쪽만 지우면 반드시 깨진다.

_TEMPLATE = _REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


def _template_text() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("item", cpb.REQUIRED_CHECKS)
def test_every_required_check_exists_in_template_literally(item):
    """필수 항목이 템플릿에 리터럴로 없으면 저자가 체크할 칸 자체가 없다."""
    assert f"- [ ] {item}" in _template_text(), (
        f"REQUIRED_CHECKS의 '{item}'가 템플릿에 없다 — 저자는 이 항목을 체크할 수 "
        f"없고, 머지는 전량 체크를 요구하므로 모든 PR이 머지 불가가 된다."
    )


def test_template_has_no_check_absent_from_required():
    """템플릿에만 있는 항목은 아무도 강제하지 않는 죽은 문구다."""
    items = set(re.findall(r"^\s*-\s*\[[ xX]\]\s*(.+?)\s*$", _template_text(), re.M))
    # 변경 유형의 체크박스(이모지 목록)는 REQUIRED_CHECKS 대상이 아니다.
    checklist = {i for i in items if not i.startswith(("🐛", "✨", "♻️", "📝", "🔧"))}
    assert checklist == set(cpb.REQUIRED_CHECKS)


@pytest.mark.parametrize("name", tuple(cpb.SECTION_BUDGETS) + cpb.EXEMPT_SECTIONS)
def test_every_gate_section_exists_in_template(name):
    """게이트가 아는 섹션은 템플릿에 있어야 한다 — 없으면 저자가 못 쓴다."""
    assert f"## {name}" in _template_text()


def test_template_itself_declares_only_known_sections():
    """템플릿에 게이트가 모르는 섹션이 있으면 그 템플릿으로 쓴 PR이 전부 리젝된다."""
    sections = set(re.findall(r"^##\s+(.+?)\s*$", _template_text(), re.M))
    allowed = set(cpb.SECTION_BUDGETS) | {cpb.CHECKLIST_SECTION} | set(cpb.EXEMPT_SECTIONS)
    assert sections <= allowed, f"템플릿에 게이트가 모르는 섹션: {sections - allowed}"
