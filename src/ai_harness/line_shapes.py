#!/usr/bin/env python3
# BLUF: 산문 형태(shape) 판정 — 펜스·문장 경계·체크박스·이슈 참조·예산 파싱 문법(stdlib only, 의존성 0) — check_doc_form.py·check_pr_body.py·relink_docs.py·gate_config.py가 순환 임포트 없이 공유하는 leaf 모듈.
"""줄 형태(shape) 판정 — 펜스·문장 경계·체크박스·이슈 참조·예산 파싱 문법.

`check_doc_form.py`(문서 폼 게이트)·`check_pr_body.py`(PR 본문·코멘트 게이트)·
`relink_docs.py`(링크 재작성기)·`gate_config.py`(`build_exempt_shape()`)가 이
모듈을 공유한다. 애초엔 체크박스·이슈 참조 판정만 있었다(그 하나의 소비처인
`gate_config.py`를 위해 두 게이트 모듈이 서로를 참조하는 순환을 피하는 것이
동기였다). 이후 두 게이트 파일에 전재돼 있던 펜스·문장 경계 판정과 예산
파싱 정규식도 이관해, "산문 형태 판정"이라는 이 모듈의 선언을 실제로 채웠다.

격리 원칙("게이트가 게이트를 import하지 않는다")은 이 leaf 모듈 공유와
충돌하지 않는다 — 정규식과 판정 로직이 여기 한 곳에 있고, 두 게이트가
서로를 참조하지 않는 것은 그대로다.
"""
from __future__ import annotations

import re

# --- 코드펜스 ----------------------------------------------------------------

# 백틱·틸드 두 펜스 문법을 다 받는다(CommonMark는 둘 다 허용). 저장소 전체에서
# 펜스 판정 정규식은 이 한 곳에만 있다 — 예전엔 check_doc_form.py·check_pr_body.py·
# relink_docs.py 세 곳이 각자 정규식을 들고 있었고, 그중 relink_docs.py만 틸드를
# 인식해 같은 저장소 안에서 판정이 갈렸다(실측 결함).
_FENCE_LINE = re.compile(r"^\s*(?:```|~~~)")


def is_fence_line(line: str) -> bool:
    """줄이 코드펜스 여는/닫는 줄(백틱 또는 틸드)인지 — 토글 판정에 쓴다.

    **CommonMark 완전판이 아니다** — 여는 펜스와 닫는 펜스의 길이 일치·문자
    일관성은 검사하지 않는다. 판정은 "이 줄이 펜스로 시작하는가" 하나뿐이다.
    """
    return bool(_FENCE_LINE.match(line))


# --- 문장 경계 -----------------------------------------------------------------

# 문장 종결 부호 — 비숫자 뒤 `[.?!] ` + 그 뒤에 다음 문장(비공백)이 이어질 때.
# 이게 산문 줄 안에 있으면 한 줄에 문장이 여럿이라는 뜻이다(흐름 우겨넣기).
# - 마침표뿐 아니라 물음표·느낌표도 종결로 본다(실측: reviewer-direction.md에
#   물음표 유형 문장 경계 미검출 사례가 있었다).
# - 앞이 숫자·마침표면 배제 → 소수(0.85)·번호(1. )·말줄임(`...`)이 안 걸린다.
# - 뒤가 공백 아니면 배제 → 코드(config.py)·경로가 안 걸린다.
# - 뒤가 줄 끝/참조뿐이면 배제 → "불변 서술. [✅ test]"는 한 문장이라 통과
#   (검증 참조를 뺀 measured가 "…. "로 끝나 다음 문장이 없다).
# 80자(길이 프록시)와 병존 — 이건 구조를 강제한다.
#
# 한계(정직 표기, 실측): 종결 부호 뒤에 공백이 없으면 못 잡는다 — 산문에서
# 문장경계를 규칙만으로 완전히 뽑을 수는 없다(게이트는 볼 수 있는 것만
# 판정한다, 무한 대상). `e.g.`·`U.S.` 같은 영문 약어 표기는 이 정규식의
# 오탐 후보다(마침표 뒤 공백 + 다음 문장을 진짜 문장 종결로 오인).
#
# 재판정 트리거(정직 표기): 지금은 이 저장소·형제 저장소 문서 전체에 그런
# 영문 약어 표기가 없어 오탐이 실측되지 않았을 뿐이다 — 없다는 사실이 이
# 게이트를 정당화하지 않는다. 그런 표기가 산문에 실제로 등장해 오탐으로
# 걸리는 순간이 재판정 시점이다(주기 재판정이 아니라 관측 시점 재판정).
# 그 전까지는 유지한다.
_SENTENCE_END = re.compile(r"(?<![0-9.])[.?!] (?=\S)")


def has_sentence_boundary(text: str) -> bool:
    """한 줄(혹은 그 사본)에 문장 종결이 하나 이상 있는지 — "한 줄 한 문장"
    규칙의 판정 본체. 위 한계·재판정 트리거가 이 함수에 그대로 걸린다."""
    return bool(_SENTENCE_END.search(text))


# --- 예산 파싱 문법 ------------------------------------------------------------

# 폼 문구 관례를 읽는 정규식 — **함수로 감싸지 않고 그대로 공개한다.** 이
# 모듈의 다른 정규식(펜스·문장·체크박스·이슈 참조)은 전부 비공개고 참거짓
# 함수만 공개하는데, 이 둘만 예외다 — 호출자가 `.group(1)`로 수치를 뽑아야
# 하므로 참거짓 함수로 감싸면 정보(수치 자체)가 사라진다.
#
# 실제 폼 문구는 "100줄 · 산문 한 줄 80자 · BLUF 한 줄 100자(마커 제외)."이지
# "…이하" 접미사가 없다 — 접미사를 요구하면 폼 전부 매칭 실패로 예산이 항상
# 빈 dict가 되어 게이트가 조용히 무력화된다(회귀 방지).
LINE_CHARS_PATTERN = re.compile(r"산문 한 줄 (\d+)자")
MAX_LINES_PATTERN = re.compile(r"(\d+)줄")


def extract_budgets(text: str, patterns: dict[str, re.Pattern[str]]) -> dict[str, int]:
    """폼 문구에서 예산 표를 뽑는다. 호출자가 자기 키 집합(`patterns`)을 넘긴다.

    키 집합과 폼 파일 경로는 호출자마다 다르다(check_doc_form.py는
    `bluf_chars`를 더 가지고, 폼 파일 위치도 서로 다르다) — 그래서 이 함수는
    그 둘을 모르고 오직 "패턴으로 찾아 수치로 변환"만 한다. 못 찾은 키는
    출력에서 빠진다(호출자가 fail-closed 판단을 스스로 한다).
    """
    out: dict[str, int] = {}
    for key, pat in patterns.items():
        m = pat.search(text)
        if m:
            out[key] = int(m.group(1))
    return out


# --- 체크박스·이슈 참조 --------------------------------------------------------
#
# `gate_config.py`(`build_exempt_shape()`)의 유일한 소비처를 위해 뽑혔다 — 그
# 하나의 소비처를 위해 `check_pr_body.py`와 `gate_config.py`가 서로를
# 참조하게 두는 대신, 이 leaf 모듈로 양쪽 다 최상단에서 평범하게 import한다
# (stdlib only 제약 안에서 순환 제거).

# 기계가 판정 못 하는 항목의 자기신고 섹션. 예산 대상이 아니다(문구가 고정이라
# 저자가 줄일 수 없다). **이 섹션은 강제가 아니라 자기보고다** — 자기보고
# 불신이 겨냥하는 바로 그 형태이므로, 여기 체크가 곧 사실이라고 읽어서는 안 된다.
CHECKLIST_SECTION = "확인"

# 체크박스 줄. 들여쓴 하위 항목도 받는다(중첩이 곧 위반이 되면 안 된다).
_CHECKBOX_LINE = re.compile(r"^\s*-\s*\[[ xX]\]\s+\S")

# 이슈 참조 토큰 — `#12`, `owner/repo#12`, 그리고 GitHub이 링크하는 전체 URL.
# `repo#12`(레포명만)는 일부러 뺐다: GitHub이 자동 링크하지 않아 독자가 못 따라간다.
_REF_TOKEN = re.compile(
    r"https?://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/(?:issues|pull)/\d+"
    r"|(?:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)?#\d+"
)
# 종료 키워드. GitHub이 인식하는 것만.
#
# **긴 대안을 먼저** 둔다. 정규식 대안은 왼쪽부터 먹으므로 `Clos(?:e|es|ed)`로 쓰면
# "Closes"에서 "Close"만 먹고 "s"를 남긴다 — 매칭 위치가 고정된 `.sub()`는 앵커
# 있는 매칭과 달리 되짚지 않는다. 남은 "s"가 산문으로 오인돼 정상 참조가 리젝됐다.
_REF_KEYWORD = re.compile(
    r"Closed|Closes|Close|Fixed|Fixes|Fix|Resolved|Resolves|Resolve|Refs|Ref|and",
    re.IGNORECASE,
)


def is_issue_ref_line(line: str) -> bool:
    """줄 전체가 이슈 참조로만 이뤄졌는지 — 참조 여러 개도 받는다.

    `Closes #1, #2`·`Closes #1, closes #2`·이슈 URL은 GitHub이 정상 링크하는 표준
    표기라 받아야 한다(정규식으로 "한 줄에 하나"를 강요하면 게이트가 아니라 족쇄가
    된다 — 리뷰 지적). 참조 토큰·키워드·구분자를 걷어내고 **남는 게 있으면**
    그건 산문이므로 리젝한다.

    `gate_config.py`가 `EXEMPT_SHAPE`를 구성할 때 이 이름을 직접 import한다 —
    공개 함수(밑줄 없음)로 둔 이유가 그것이다.
    """
    if not _REF_TOKEN.search(line):
        return False
    rest = _REF_KEYWORD.sub("", _REF_TOKEN.sub("", line))
    return re.sub(r"[\s,;\-·]+", "", rest) == ""


def is_checkbox_line(line: str) -> bool:
    """줄이 체크박스 형식(`- [ ] ...`/`- [x] ...`)인지 — 면제 섹션 형태 검증에 쓴다.

    `is_issue_ref_line`과 같은 이유로 공개 함수다 — `gate_config.py`가 이
    이름을 직접 import해 `EXEMPT_SHAPE`를 만든다.
    """
    return bool(_CHECKBOX_LINE.match(line))
