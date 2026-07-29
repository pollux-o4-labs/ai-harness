#!/usr/bin/env python3
# BLUF: 체크박스 줄·이슈 참조 줄의 형태 판정(stdlib only, 의존성 0) — check_pr_body.py와 gate_config.py가 순환 임포트 없이 공유하도록 분리한 모듈.
"""줄 형태(shape) 판정 — 체크박스·이슈 참조.

`check_pr_body.py`(PR 본문 게이트 core)와 `gate_config.py`(레포별 설정의
`build_exempt_shape()`)가 둘 다 이 판정 로직을 쓴다. 이 두 함수·정규식은
`check_pr_body.py` 자기 로직에서는 한 번도 호출되지 않는다 — 유일한 소비처는
`gate_config.build_exempt_shape()`뿐이다. 그 하나의 소비처를 위해 두 모듈이
서로를 참조하게 두는 대신, 이 모듈로 뽑아 양쪽 다 최상단에서 평범하게
import할 수 있게 한다(stdlib only 제약 안에서 순환 제거).
"""
from __future__ import annotations

import re

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
