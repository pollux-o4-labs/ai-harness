#!/usr/bin/env python3
# BLUF: 게이트 core(check_pr_body.py·check_doc_form.py)의 repo별 설정값 — 이 파일만 레포마다 다르고 나머지 게이트 코드는 전 레포에서 바이트 동일해야 한다.
"""게이트 설정 — repo별 특화 지점.

`check_pr_body.py`·`check_doc_form.py`·`gen_readmes.py`(core)는 이 저장소든
다른 저장소든 로직이 같아야 한다 — 대상 저장소에 맞출 값(은어 목록·면제 섹션·
규칙 문서 인용)은 전부 이 파일로 뽑는다. 이러면 core를 복사해 쓰는 저장소가
늘어도 core 파일 자체는 안 갈라지고, 이 파일 하나만 그 저장소 것으로 바꾸면
된다(도입기: `scripts/check_gate_drift.py`가 core만 바이트 비교하고 이 파일은
비교에서 뺀다 — 다르라고 만든 파일이라 드리프트가 아니다).

**`EXEMPT_SHAPE`는 core의 검증 함수를 직접 import해서 만든다** — 이름 문자열로
찾는 registry가 아니다. 이름→함수 registry는 오타가 나도 "그 이름이 없다"는
런타임 조회 실패로만 드러나 늦게 터진다. 직접 import는 오타가 나면 그 즉시
`ImportError`로 죽는다(fail-loud) — registry가 아니라 하나 아낀 안전장치다.

**그 import는 이 파일 맨 위가 아니라 `build_exempt_shape()` 안에 있다**(지연
임포트) — check_pr_body.py가 이 파일을 임포트하고, 이 파일은 check_pr_body.py를
임포트하는 순환이라 맨 위에 두면 어느 쪽이 먼저 로드되느냐에 따라 임포트가
깨진다. check_doc_form.py처럼 이 파일의 `RULE_*` 값만 쓰고 `build_exempt_shape`는
안 부르는 코드는 이 함수를 부르기 전까진 check_pr_body.py를 끌어들이지 않는다.
"""
from __future__ import annotations

from typing import Callable

# 제3자가 한 번에 못 읽는 이 저장소의 내부 용어 — 첫 등장에 괄호 풀이를 요구한다
# (금지가 아니다. 그 용어가 주제인 PR을 못 쓰게 되면 게이트가 꺼진다).
# **완결 목록이 아니라 상습범 목록이다** — 여기 없는 은어가 통과하는 게 정상이고,
# 일반적 가독성은 리뷰어 판정에 남는다. 새 상습범은 관측되는 대로 여기 추가한다
# (목록은 바닥이지 증명이 아니다).
JARGON_TERMS: tuple[str, ...] = (
    "L2", "seam", "BLUF", "altitude", "provenance", "ship-ok",
    "도그푸딩", "워터마크", "서브레포", "폴백", "밴드에이드", "원장",
    "청킹", "인제스트", "델타갱신", "스튜어드",
    "fail-open", "fail-closed", "캐스케이드",
)

# check_doc_form.py의 자동생성 블록 마커 — core는 `BLUF-INDEX`(gen_readmes.py
# 롤업) 하나만 안다. 저장소가 자체 멱등 splice 도구(예: 온보딩 스크립트)를
# 갖췄으면 그 시작/끝 마커 쌍을 여기 추가한다 — **비어 있는 게 기본이다**(그런
# 도구가 없는 저장소에서 남의 마커 이름이 core에 하드코딩돼 있으면 죽은
# 참조다). core의 `_AUTOGEN_MARKERS`가 이 튜플을 자기 것과 이어 붙인다.
EXTRA_AUTOGEN_MARKERS: tuple[tuple[str, str], ...] = ()

# 글자 예산 대신 **형태**로 강제하는 섹션 — 조직 공용 템플릿(org `.github` 레포의
# pull_request_template.md)에서 온 표준 골격이다.
#
# 예산을 안 먹이는 근거는 "내용이 정해진 형태라 저자가 줄일 몫이 아니다"인데, 그
# 전제를 말로만 두면 근거가 거짓이 된다 — 산문을 여기 옮겨 적는 순간 예산이 무제한
# 우회된다(적대 리뷰 실측: 이 섹션을 도입한 PR 자신이 첫 사용자였다. 넘친 산문 한
# 줄을 `관련 이슈`로 옮겨 300자 천장을 통과했고, 되돌리면 357자로 리젝됐다).
#
# 그래서 전제를 코드로 강제한다(EXEMPT_SHAPE): 형태에 안 맞는 줄이 있으면 리젝.
# 이러면 예산을 안 먹여도 산문이 못 들어오므로 면제 근거가 비로소 참이 된다.
#
# **필수가 아니다** — org 템플릿 자신이 "해당 없는 섹션은 지워도 됩니다"를 계약으로
# 두므로, 여기서 존재를 강제하면 그 계약을 깬다. 강제하는 건 존재가 아니라 형태다.
#
# **org 템플릿이 다른 저장소로 이식할 땐 이 튜플만 그 조직 템플릿에 맞춰 바꾼다**
# — 아래 EXEMPT_SHAPE도 같이 바꿔야 한다(섹션 이름이 짝을 이룬다).
EXEMPT_SECTIONS: tuple[str, ...] = ("변경 유형", "관련 이슈")

# 섹션명 → (허용 판정, 위반 시 처방). **예산이 없는 섹션은 예외 없이 여기 있어야
# 한다** — 예산도 형태도 없는 섹션은 곧 산문 창고이기 때문이다(저자가 예산 넘칠
# 때마다 넘친 문장을 거기로 옮기면 된다). 실측으로 두 번 당했다: (1) 형태
# 미정의 면제 섹션에 3000자 → 위반 0, (2) `확인` 섹션 뒤에 산문 626자 → exit 0
# 통과. `확인`은 **필수**라 항상 존재하고 렌더링도 되므로 `관련 이슈`보다 더
# 좋은 은신처였다. 이 불변식은 코드로 고정한다 —
# tests/test_check_pr_body.py::test_every_non_budget_section_has_a_shape.
def build_exempt_shape() -> dict[str, tuple[Callable[[str], bool], str]]:
    """EXEMPT_SECTIONS 각 섹션의 허용 형태를 만들어 반환한다.

    check_pr_body.py를 여기(함수 안)에서 임포트한다 — 모듈 맨 위에서 임포트하면
    순환(check_pr_body.py → gate_config.py → check_pr_body.py)이 어느 쪽이
    먼저 로드되느냐에 따라 깨진다. check_pr_body.py는 자기 검증 함수
    (`is_checkbox_line`·`is_issue_ref_line`)를 정의한 **뒤** 이 함수를 불러
    EXEMPT_SHAPE를 채운다 — 그 시점엔 이 두 이름이 이미 있으므로 이 지연
    임포트가 항상 성립한다.
    """
    from check_pr_body import CHECKLIST_SECTION, is_checkbox_line, is_issue_ref_line

    return {
        "변경 유형": (
            is_checkbox_line,
            "체크박스 줄(`- [x] ...`)만 쓸 수 있다",
        ),
        "관련 이슈": (
            is_issue_ref_line,
            "줄 전체가 이슈 참조여야 한다 — `Closes #12`·`Refs owner/repo#12`·"
            "`Closes #1, #2`·이슈 URL은 되고, 참조 옆에 덧붙인 설명은 안 된다"
            "(백틱으로 감싸면 GitHub이 링크를 안 걸어 리젝된다)",
        ),
        CHECKLIST_SECTION: (
            is_checkbox_line,
            "체크박스 줄만 쓸 수 있다 — 이 절은 자기신고 칸이지 설명 칸이 아니다",
        ),
    }

# --- 문서 포인터 · 규칙 인용 -------------------------------------------------
#
# core의 리젝 메시지 중 일부는 "이 판정의 근거 조문"을 괄호로 인용한다. 그
# 조문 번호·문서 경로는 저장소마다 다른 규칙 문서(docs/rules/*)에 딸린 값이라
# core에 박으면 규칙 문서가 없는 저장소에서 죽은 인용이 남는다(가리키는 문서가
# 없다). **이 저장소는 아직 docs/rules가 없다** — 그래서 전부 공란이다. 값이
# 공란이면 core가 그 인용을 통째로 생략한다(문장은 인용 없이도 완결되게 짜여
# 있다) — 채워 넣으면 그 순간부터 인용이 켜진다.
RULE_DOC_AUTHORING = ""     # 문서 저작 규칙(재서술 금지·한 줄 한 문장·비대 상한 등)
RULE_REVIEW_EVIDENCE = ""   # 리뷰 근거 기록 규칙("근거 없는 체크 금지")


def rule_cite(base: str, article: str = "") -> str:
    """`base`(위 RULE_* 값)가 있으면 `(base article)` 괄호를 만들고, 없으면
    빈 문자열 — 규칙 문서가 없는 저장소에서 죽은 인용이 안 남게 한다(그
    저장소가 문서를 갖추면 이 파일의 RULE_* 값만 채우면 인용이 켜진다).

    check_pr_body.py·check_doc_form.py가 둘 다 쓰는 순수 헬퍼라 여기 하나로
    모은다 — 지연 임포트가 필요 없다(check_pr_body.py를 끌어들이지 않는다).
    """
    if not base:
        return ""
    return f"({base}{' ' + article if article else ''})"
