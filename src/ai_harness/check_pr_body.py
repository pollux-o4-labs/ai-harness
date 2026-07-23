#!/usr/bin/env python3
# BLUF: PR 본문이 필수 섹션을 갖췄고 각 섹션이 글자 예산 안인지, PR 제목이 conventional-commit 형식인지 판정하는 룰 게이트(stdlib only, LLM 0) — Claude Code PreToolUse 훅으로 `gh pr create`·`gh pr merge`를 리젝한다.
"""PR 본문 구조·분량·제목 게이트.

`gh pr create`로 올라가는 본문이 `.github/PULL_REQUEST_TEMPLATE.md`의 섹션을
갖췄는지, 각 섹션이 예산 안인지 검사한다. 언어 지시("짧게 써라")가 안 지켜지므로
구조로 강제한다. `gh pr merge`도 같은 검사기로 리젝한다 — 대상 PR의
현재 본문을 `gh pr view --json body`로 조회해 판정한다("머지는 사용자 몫" 규약을
처음 기계로 강제한다). create는 제목도 검사한다 — `type(scope)?: subject`
conventional-commit 형식(`check_pr_title`, S5).

**create와 merge의 차이(확인 체크리스트)**: create는 리뷰 요청 시점이라 리뷰어가
아직 체크를 못 했다 — 형식(섹션·분량·은어·문장·제목)만 강제하고 확인 절은 '존재'만
본다. merge는 리뷰가 끝난 뒤라 확인 절 '전량 체크'까지 요구한다. 이러면 "PR
올려 리뷰받고 → 리뷰어가 체크 → 머지"가 성립한다.

**예산을 섹션별로 쪼갠 이유**: 총량만 걸면 저자가 어느 섹션을 죽일지 스스로
고른다 — 서사가 붙기 쉬운 요약이 부풀고, 리뷰어에게 정작 필요한 검증·범위밖이
0자가 된다. 섹션별 상한은 그 선택권을 뺏는다.

**모드**:
  ai-harness check-pr --body-file BODY.md   # CLI 검사(exit 1 = 위반)
  ai-harness check-pr --hook                # Claude Code PreToolUse
                                            # (stdin=훅 JSON, exit 2 = 리젝)
  ai-harness check-pr --merge-check <PR>    # 머지 준비 dry-run(실제
                                            # 머지 안 함, exit 1 = 미준비)

훅 모드는 본문을 못 들여다보는 호출(`--fill`, 에디터 대화형, `gh pr merge`의
`gh pr view` 조회 실패 등)도 리젝한다(fail-closed) — 검사를 우회할 수 있으면
게이트가 아니다(자기보고 불신).

**`--merge-check`는 머지 전에 사람이 미리 돌려보는 dry-run이다.** `gh pr merge`
자체를 부르지 않는다 — 체크리스트 전량 채움 + 리뷰 근거 규칙(있는 저장소는
`gate_config.RULE_REVIEW_EVIDENCE`가 조문을 인용한다)이 요구하는 리뷰 종합
코멘트의 존재·신선도(최신 코멘트의 SHA == 현재 head)를 한 번에 판정한다. `gh pr
merge` 훅 경로도 이 코멘트 존재·신선도 검사를 같이 태운다(백스톱,
`check_review_evidence`) — 체크리스트가 전량 체크돼도 근거 코멘트가 없거나
낡았으면 리젝한다.

**`gh pr comment`는 다른 검사를 받는다.** 코멘트는 리뷰 항목별 근거 기록이지
PR 본문이 아니다 — 섹션 골격(요약/변경/범위 밖/검증)·체크리스트는 적용하지
않는다. 대신 그 코멘트 자체가 나중에 읽어야 할 근거 문서가 되므로 분량·문장
구조는 그대로 강제하고(`docs_format/pr-comment.md`의 줄수·줄자수 예산),
내부 용어 풀이(`JARGON_TERMS`)도 그대로 적용한다 — 체크리스트의 은어 검수
항목은 "PR에 작성된 글" 전체가 대상이고 코멘트도 그 글이기 때문이다.

  gh pr create    섹션·예산·용어·체크절(존재만)·제목(conventional-commit)
  gh pr merge     위 + 체크 전량(제목은 이미 만들어진 PR을 가리킬 뿐이라 검사 안 함)
  gh pr comment   줄자수·줄수 예산 + 한 줄 한 문장 + 용어 풀이(섹션·체크리스트 없음)

(comment 예산 수치는 `docs_format/pr-comment.md`가 정본 — 여기 재서술 안 함.)

**레포별 설정은 `gate_config.py`에 있다** — 은어 목록·면제 섹션·규칙 인용처럼
저장소마다 달라야 하는 값은 이 core에 안 둔다. core는 설치된 패키지 하나가
정본이고, 대상 저장소는 자기 `gate_config.py`만 두면 CLI가 그 값을 얹는다.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

# 이 dict가 PR 본문 예산의 정본이다 — 문서·템플릿은 이 값을 재서술하지 말고
# 이 파일을 가리킬 것. 위반 메시지가 실측값과 함께 예산을 알려주므로 저자는
# 여기를 안 읽어도 된다.
SECTION_BUDGETS: dict[str, int] = {
    "요약": 150,
    "변경": 300,
    "범위 밖": 100,
    "검증": 150,
}

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

_NONE_LINE = re.compile(r"^\s*(?:없음|N/?A)\s*$", re.IGNORECASE)


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


# --- 레포별 설정(gate_config.py) --------------------------------------------
#
# `build_exempt_shape()` 호출은 반드시 위 두 함수·CHECKLIST_SECTION이 정의된
# **뒤**에 와야 한다 — 그 함수가 이 파일을 거꾸로 import해(`from check_pr_body
# import is_checkbox_line, ...`) EXEMPT_SHAPE를 만드는데, 그 시점에 이 두
# 이름이 이미 이 모듈에 있어야 순환 임포트가 성립한다(파이썬은 부분 초기화된
# 모듈이라도 이미 실행된 만큼의 이름은 내준다). gate_config.py가 그 import를
# 모듈 맨 위가 아니라 함수 안에 지연시켜 두므로, 이 파일이 gate_config.py보다
# 나중에 로드되는 순서(아래)뿐 아니라 먼저 로드되는 순서(gate_config.py를
# 다른 스크립트가 먼저 불렀을 때)도 안전하다.
from ai_harness.gate_config import (  # noqa: E402
    EXEMPT_SECTIONS,
    JARGON_TERMS,
    RULE_REVIEW_EVIDENCE,
    build_exempt_shape,
    rule_cite as _rule_cite,
)

_EXEMPT_SHAPE = build_exempt_shape()


# 문장 종결 마침표 — check_doc_form과 동일 규칙("한 줄 한 문장")이다. 두
# 스크립트는 stdlib only(훅에서 별도 설치 없이 돈다)라 import로 합칠 수 없어
# 정규식을 복제한다. 앞이 숫자·마침표면 배제(소수·번호·말줄임), 뒤가 공백
# 아니면 배제(코드·경로), 뒤에 다음 문장(비공백)이 이어질 때만 걸린다.
_SENTENCE_END = re.compile(r"(?<![0-9.])\. (?=\S)")
REQUIRED_CHECKS: tuple[str, ...] = (
    "가독성을 높이는 검수를 진행했다 (PR body 및 comment 대상)",
    "과한 내부 은어 사용 검수했다",
    "비전문가, 제3자도 쉽게 이해할 수 있도록 작성되었는지 검토했다",
    # 운영문서 stale을 별도 이슈로 떼면 원 PR과 분리돼 드리프트가 방치되기 쉽다
    # (드리프트는 기계 린트가 아니라 그 문서를 건드린 작업자가 그 자리에서 잡는다).
    "이 변경이 다른 문서를 낡게 하지 않았는지, 작업 중 발견한 기존 stale은 고쳤는지 검토했다 (PR이 영향을 주는 문서들)",
    "바꾼 값·사실을 옮겨 적은 다른 문서도 같이 고쳤는지 확인했다",
    "이 문서를 가리키던 링크·참조가 끊기지 않았는지 확인했다",
    "영향받는 문서의 요약(맨 위 한 줄)이 여전히 맞는지 확인했다",
    # 아래 2개는 org 공용 템플릿의 체크리스트에서 왔다 — 우리 목록이 문서 정합에만
    # 쏠려 있어 코드 변경의 자기신고 축(테스트·호환성)이 비어 있었다. 나머지 org
    # 항목(self-review·관련 문서 갱신)은 위 항목과 겹쳐 옮기지 않았다(재서술 금지).
    "필요한 테스트를 추가하거나 갱신했다",
    "동작을 깨는 변경(breaking change)이라면 본문에 명시했다",
)

# `gh pr comment` 예산의 정본 — 이 dict는 이 파일에 없다. check_doc_form의
# _BUDGET_PATS와 같은 문구 관례를 파싱하지만, 두 스크립트는 stdlib only 제약
# (훅에서 별도 설치 없이 돈다)이라 import로 못 합쳐 정규식을 복제한다(위
# _SENTENCE_END와 같은 이유). 폼 파일이 없으면 코멘트 게이트·리뷰 근거 검사가
# fail-closed로 리젝한다(우회가 아니라 "아직 안 채운 설정"임을 알리는 것) —
# 저장소가 이 경로에 폼 파일을 작성하면 그때부터 켜진다.
_COMMENT_FORM_PATH = (
    Path(__file__).resolve().parent / "docs_format" / "pr-comment.md"
)
_COMMENT_BUDGET_PATS = {
    "line_chars": re.compile(r"산문 한 줄 (\d+)자"),
    "max_lines": re.compile(r"(\d+)줄"),
}

# 리뷰 종합 코멘트 헤더 접두어("## 리뷰 종합") — pr-comment.md의 예시 문구
# (`## 리뷰 종합 — 2차 (8c8f4f7)`)에서 뽑는다. 헤더 관례가 바뀌면 폼 파일만
# 고치면 되고 이 스크립트는 안 건드린다.
_REVIEW_HEADER_EXAMPLE = re.compile(r"`(##\s+.+?)\s*—\s*\d+차\s*\([0-9a-fA-F]+\)`")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_GLOSS_AFTER = re.compile(r"^\s*[(（]")
# 코멘트 줄 검사용 펜스 토글 — check_doc_form.py의 _FENCE와 같은 정규식이지만
# 위와 같은 이유(stdlib only)로 복제한다.
_FENCE_LINE = re.compile(r"^\s*```")
_CHECKED_ITEM = re.compile(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$")


def strip_html_comments(text: str) -> str:
    """템플릿 힌트 주석을 제거 — 힌트는 예산을 먹지 않고, 남겨둬도 본문이 아니다."""
    return _HTML_COMMENT.sub("", text)


def measure(text: str) -> int:
    """섹션 분량(글자수). 공백은 연속 1칸으로 정규화해 줄바꿈 들여쓰기가 예산을
    먹지 않게 한다 — 재는 대상은 저자가 쓴 내용이지 레이아웃이 아니다."""
    return len(" ".join(text.split()))


def strip_code(text: str) -> str:
    """코드펜스·인라인코드 제거 — 은어 검사 대상은 산문이지 명령어가 아니다.
    (분량 예산은 반대로 코드까지 센다 — 로그를 붙일 자리가 아니라 명령+종료코드
    자리이므로 예산 안에 들어와야 한다.)"""
    return _INLINE_CODE.sub("", _FENCED_CODE.sub("", text))


def check_jargon(body: str) -> list[str]:
    """내부 용어의 첫 등장에 괄호 풀이가 붙었는지 검사한다."""
    text = strip_code(strip_html_comments(body))
    violations: list[str] = []
    for term in JARGON_TERMS:
        idx = text.find(term)
        if idx == -1:
            continue
        if not _GLOSS_AFTER.match(text[idx + len(term):]):
            violations.append(
                f"내부 용어 '{term}'에 풀이가 없음 — 첫 등장을 "
                f"'{term}(쉬운 말 설명)' 형태로 풀어라. 배경지식 없는 "
                f"제3자가 한 번에 읽어야 한다."
            )
    return violations


def parse_sections(body: str) -> dict[str, str]:
    """`## <제목>` 기준으로 본문을 섹션으로 가른다. 제목 중복 시 뒤가 이긴다."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in strip_html_comments(body).splitlines():
        m = _H2.match(line)
        if m:
            current = m.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def check_checklist(sections: dict[str, str]) -> list[str]:
    """`확인` 섹션의 필수 항목이 모두 체크됐는지 본다.

    **이 검사가 재는 것은 글이 아니라 글자 'x'다.** 체크를 받았다는 사실은
    항목이 참이라는 증거가 아니다 — 판정은 여전히 리뷰어 몫이다.
    """
    if CHECKLIST_SECTION not in sections:
        return [f"섹션 '## {CHECKLIST_SECTION}' 없음 — 체크리스트는 필수다."]
    checked = {
        m.group(1)
        for line in sections[CHECKLIST_SECTION].splitlines()
        if (m := _CHECKED_ITEM.match(line))
    }
    return [
        f"체크 안 됨 — '- [x] {item}'"
        for item in REQUIRED_CHECKS
        if item not in checked
    ]


def check_checklist_present(sections: dict[str, str]) -> list[str]:
    """`확인` 섹션이 있는지만 본다(항목 체크 여부는 안 본다).

    PR 생성 시점은 **리뷰 요청**이라 리뷰어가 아직 체크를 못 했다 — 이때 완료를
    요구하면 리뷰 전에 작성자가 자기 체크를 강제당해 "리뷰→체크" 흐름이 깨진다.
    완료(모든 항목 체크)는 머지 시점(check_checklist)에서 요구한다."""
    if CHECKLIST_SECTION not in sections:
        return [f"섹션 '## {CHECKLIST_SECTION}' 없음 — 체크리스트는 필수다."]
    return []


def check_sentences(sections: dict[str, str]) -> list[str]:
    """예산 섹션의 산문 한 줄에 문장이 여럿이면 리젝 — 한 줄 한 문장.

    사항을 한 불릿에 몰아넣지 말고 문장마다 줄바꿈해 구조화하라는 규칙이다.
    자동변환은 안 한다(들여쓰기는 의미라 기계가 틀린다) — 저자가 다듬는다.
    """
    violations: list[str] = []
    for name in SECTION_BUDGETS:
        if name not in sections:
            continue
        clean = strip_code(strip_html_comments(sections[name]))
        for i, line in enumerate(clean.splitlines(), 1):
            if _SENTENCE_END.search(line):
                violations.append(
                    f"섹션 '## {name}' {i}번째 줄에 문장이 여럿 — "
                    f"문장마다 줄바꿈해 불릿로 빼라(마침표 뒤에서 끊는다)."
                )
    return violations


def check_exempt_shape(sections: dict[str, str]) -> list[str]:
    """면제 섹션이 정해진 형태만 담았는지 — 예산을 안 먹이는 대가로 형태를 강제한다.

    이 검사가 없으면 면제 섹션은 무제한 산문 창고가 되고, 저자는 예산이 넘칠 때마다
    넘친 문장을 이리로 옮기면 된다(예산 게이트 무력화). 형태를 막으면 옮길 자리가
    없어져 저자는 실제로 줄이는 수밖에 없다.
    """
    violations: list[str] = []
    for name, (is_allowed, hint) in _EXEMPT_SHAPE.items():
        if name not in sections:
            continue
        # strip_code를 쓰면 안 된다 — 코드펜스·백틱으로 감싼 산문이 **사라져서**
        # 섹션이 비어 보이고 그대로 통과한다(자가 공격으로 실측한 우회구). 은어·문장
        # 검사는 "코드는 산문이 아니다"라 벗겨내는 게 맞지만, 형태 검사는 반대다 —
        # 코드펜스 줄 자체가 이 섹션에 올 수 없는 형태이므로 그대로 봐야 잡는다.
        # HTML 주석만 벗긴다(렌더링되지 않아 독자에게 안 보이므로 내용이 아니다).
        clean = strip_html_comments(sections[name])
        for i, line in enumerate(clean.splitlines(), 1):
            if not line.strip() or _NONE_LINE.match(line):
                continue  # 빈 줄·'없음'은 어느 섹션에서나 유효한 내용이다
            if not is_allowed(line):
                violations.append(
                    f"섹션 '## {name}' {i}번째 줄이 정해진 형태가 아님 — {hint}"
                    f"(해당 없으면 '없음' 또는 섹션째 삭제). 이 섹션은 글자 예산을 "
                    f"안 먹이는 **대신** 형태를 강제한다 — 설명·서사는 '## 변경'에 "
                    f"예산 안에서 써라."
                )
    return violations


def check_pr_body(body: str, require_checklist_complete: bool = True) -> list[str]:
    """위반 목록을 반환한다(빈 리스트 = 통과).

    require_checklist_complete=False(PR 생성 시점)면 확인 절 '존재'만 보고 '모든
    항목 체크'는 요구하지 않는다 — 리뷰 전이라 리뷰어가 아직 못 채운다. 머지
    시점은 True로 전량 체크를 요구한다(리뷰 끝난 뒤). 형식(섹션·분량·은어·문장)은
    두 시점 다 강제한다."""
    sections = parse_sections(body)
    violations: list[str] = []

    for name, budget in SECTION_BUDGETS.items():
        if name not in sections:
            violations.append(
                f"섹션 '## {name}' 없음 — 예산 섹션 "
                f"{len(SECTION_BUDGETS)}개는 필수다."
            )
            continue
        size = measure(sections[name])
        if size == 0:
            violations.append(
                f"섹션 '## {name}'이 비었음 — 해당 없으면 '없음'이라고 적어라."
            )
        elif size > budget:
            violations.append(
                f"섹션 '## {name}' {size}자 > 예산 {budget}자 "
                f"({size - budget}자 초과) — 판단 근거는 남기고 서사를 지워라."
            )

    violations.extend(check_sentences(sections))
    violations.extend(check_exempt_shape(sections))
    if require_checklist_complete:
        violations.extend(check_checklist(sections))
    else:
        violations.extend(check_checklist_present(sections))

    allowed = set(SECTION_BUDGETS) | {CHECKLIST_SECTION} | set(EXEMPT_SECTIONS)
    unknown = [s for s in sections if s not in allowed]
    if unknown:
        violations.append(
            f"템플릿에 없는 섹션: {', '.join(unknown)} — "
            f"허용 섹션은 {', '.join(sorted(allowed))} 뿐이다."
        )
    violations.extend(check_jargon(body))
    return violations


# --- gh pr comment 게이트 ----------------------------------------------------
#
# 코멘트는 PR 본문이 아니라 리뷰 항목별 근거 기록이다 — 섹션 골격·체크리스트는
# 적용하지 않는다. 단, 그 코멘트도 나중에 읽어야 할 문서가 되므로 분량·문장
# 구조는 그대로 강제하고, 내부 용어 풀이도 그대로 적용한다(체크리스트의 은어
# 검수 항목이 "PR에 작성된 글" 전체를 대상으로 하고 코멘트도 그 글이다).

def load_comment_budgets() -> dict[str, int]:
    """`docs_format/pr-comment.md`에서 코멘트 예산을 뽑는다.

    폼이 정본이라 수치를 여기 하드코딩하지 않는다. 못 뽑으면 빈 dict를
    반환한다 — fail-closed 판단은 check_comment가 한다.
    """
    if not _COMMENT_FORM_PATH.is_file():
        return {}
    text = _COMMENT_FORM_PATH.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for key, pat in _COMMENT_BUDGET_PATS.items():
        m = pat.search(text)
        if m:
            out[key] = int(m.group(1))
    return out


def load_review_header_prefix() -> str | None:
    """`docs_format/pr-comment.md`의 예시 문구에서 리뷰 종합 헤더 접두어를
    뽑는다(`"## 리뷰 종합 — 2차 (8c8f4f7)"` → `"## 리뷰 종합"`).

    load_comment_budgets와 같은 이유로 토큰을 이 파일에 재서술하지 않는다.
    못 뽑으면 None — fail-closed 판단은 호출자(check_review_evidence)가 한다.
    """
    if not _COMMENT_FORM_PATH.is_file():
        return None
    text = _COMMENT_FORM_PATH.read_text(encoding="utf-8")
    m = _REVIEW_HEADER_EXAMPLE.search(text)
    return m.group(1).strip() if m else None


def _review_header_pattern(prefix: str) -> re.Pattern[str]:
    """`<prefix> — <차수> (<SHA>)` 헤더 한 줄에 매치되는 정규식을 만든다.
    `round`·`sha` 그룹으로 뽑는다 — 신선도 판정은 sha만 쓴다."""
    return re.compile(
        rf"^{re.escape(prefix)}\s*—\s*(?P<round>\S+)\s*\((?P<sha>[0-9a-fA-F]+)\)\s*$"
    )


def check_comment(body: str) -> list[str]:
    """`gh pr comment` 본문의 위반 목록을 반환한다(빈 리스트 = 통과).

    섹션 골격(요약/변경/범위 밖/검증)·체크리스트는 검사하지 않는다 — 코멘트는
    PR 본문이 아니다. 강제하는 축은 분량(줄수·줄자수)·문장 구조(한 줄 한
    문장)·내부 용어 풀이(JARGON_TERMS, check_jargon 재사용)뿐이다. **닫힌**
    코드펜스 쌍 안만 줄자수·문장 검사에서 면제한다 — 명령·출력 인용은 쪼개면
    깨진다. 안 닫힌 펜스는 면제하지 않는다(fail-closed, HIGH-1) — 닫혔는지
    가드가 없으면 펜스를 열기만 하고 안 닫는 것으로 이 게이트를 통째로
    우회할 수 있다(check_doc_form.py의 렌더-신호 논리는 사람이 눈으로 markdown
    렌더를 보는 저자를 전제하는데, 이 게이트의 저자는 실행 결과만 보는
    에이전트라 그 전제가 안 선다).
    """
    budgets = load_comment_budgets()
    line_max = budgets.get("line_chars")
    lines_max = budgets.get("max_lines")

    if line_max is None and lines_max is None:
        return [
            f"코멘트 예산을 못 뽑음({_COMMENT_FORM_PATH}) — 위반이 없어서 통과가 "
            f"아니라 잴 자가 없어서 통과할 뻔한 것이다. 폼 파일·문구를 확인하라"
            f"(fail-closed)."
        ]

    violations: list[str] = []
    lines = body.splitlines()
    if lines_max is not None and len(lines) > lines_max:
        violations.append(
            f"코멘트 {len(lines)}줄 > {lines_max}줄 — 근거는 짧게, 안 줄면 "
            f"코멘트를 나눠 달아라."
        )

    # 펜스 마커 줄 번호를 먼저 모두 모으고 앞에서부터 짝짓는다 — 짝이 맞는
    # 구간만 면제고, 마지막이 홀수로 남으면(안 닫힘) 그 구간은 EOF까지 면제
    # 하지 않는다(fail-closed).
    fence_lines = [i for i, line in enumerate(lines, 1) if _FENCE_LINE.match(line)]
    exempt: set[int] = set()
    for open_i, close_i in zip(fence_lines[0::2], fence_lines[1::2]):
        exempt.update(range(open_i, close_i + 1))
    if len(fence_lines) % 2 == 1:
        violations.append(
            f"코멘트 {fence_lines[-1]}번째 줄에서 연 코드펜스(```)가 안 닫힘 — "
            f"닫히지 않은 펜스는 그 뒤 내용 전체를 검사에서 면제시켜 우회 "
            f"통로가 된다. 펜스를 닫아라."
        )

    for i, line in enumerate(lines, 1):
        if i in exempt:
            continue
        if _SENTENCE_END.search(line):
            violations.append(
                f"코멘트 {i}번째 줄에 문장이 여럿 — 문장마다 줄바꿈해 불릿로 "
                f"빼라(마침표 뒤에서 끊는다)."
            )
        if line_max is not None and len(line) > line_max:
            violations.append(
                f"코멘트 {i}번째 줄 {len(line)}자 > {line_max}자 — 한 줄에 "
                f"흐름을 우겨넣지 말고 쪼개라."
            )

    violations.extend(check_jargon(body))
    return violations


def _report_comment(violations: list[str], body: str) -> None:
    """코멘트 위반을 stderr로 보고. PR 본문 `_report`와 달리 섹션 총계가 없다
    — 코멘트는 섹션이 없는 자유 형식이다."""
    print(
        f"[check_pr_body] PR 코멘트 리젝 — 위반 {len(violations)}건:",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    print(
        "\n형식: docs_format/pr-comment.md",
        file=sys.stderr,
    )


def _report(violations: list[str], body: str) -> None:
    """위반을 stderr로 보고. 훅 모드에선 이 텍스트가 그대로 에이전트에게 간다."""
    # 총계는 예산 대상 섹션만 — 고정문구인 `확인` 체크리스트는 저자가 줄일 수
    # 없으므로 총량에 섞으면 저자가 못 건드리는 몫만큼 예산을 뺏는다.
    sections = parse_sections(body)
    total = sum(measure(sections.get(name, "")) for name in SECTION_BUDGETS)
    print(
        f"[check_pr_body] PR 본문 리젝 — 위반 {len(violations)}건 "
        f"(총 {total}자 / 예산 {sum(SECTION_BUDGETS.values())}자):",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    print(
        # 처방은 실재하는 것만 가리킨다 — 없는 문서로 보내면 저자는 고칠 길을 잃고
        # 게이트를 지운다. 섹션·예산의 정본은 이 스크립트이므로 템플릿만 가리킨다.
        "\n형식: .github/PULL_REQUEST_TEMPLATE.md (섹션·예산·형태·용어의 정본은 이 스크립트)",
        file=sys.stderr,
    )


# --- 훅 모드 ---------------------------------------------------------------

_BODY_FLAGS = {"--body", "-b"}
_BODY_FILE_FLAGS = {"--body-file", "-F"}

# 훅은 쉘 **확장 전** 명령 문자열을 받는다 — `$VAR`·`~`·백틱·`*`는 우리가 풀 수
# 없다. 이걸 "경로 없음"으로 뭉뚱그리면 본문이 멀쩡한데도 리젝돼(오탐) 사람이
# 게이트를 지운다. 풀 수 없다는 사실과 처방을 따로 말한다.
_UNEXPANDED = re.compile(r"[$`*]|^~")


def _resolve_body_file(raw: str) -> tuple[str | None, str | None]:
    """--body-file 인자를 읽는다. 반환: (body, reason_if_unreadable)."""
    if _UNEXPANDED.search(raw):
        return None, (
            f"--body-file 경로에 쉘 확장이 있음({raw}) — 훅은 확장 전 명령을 보므로 "
            f"이걸 풀 수 없다. 절대경로 리터럴로 넘겨라."
        )
    path = Path(raw)
    if not path.is_file():
        return None, f"--body-file 경로 없음({raw})"
    return path.read_text(encoding="utf-8"), None


# gh 호출 매칭·본문 탐색 공통 인프라 — create·merge·comment 셋 다 이 위에 선다.
#
# CRITICAL(실사고): 파이썬 heredoc 안의 주석 한 줄("# gh pr comment preceded by
# env assignment")이 shlex.split 결과에서 "gh","pr","comment"가 인접해 gh
# 호출로 오인됐다 — gh를 부르지도 않은 명령이 리젝됐다. **근본 해결은
# 불가능하다**: shlex는 진짜 셸 파서가 아니라 주석·heredoc·문자열 안 평문을
# 구별 못 한다. 대신 두 가지로 피해를 줄인다 — (1) --body/--body-file 탐색을
# 매칭된 gh 호출과 같은 셸 세그먼트로 좁혀 무관한 다른 명령의 플래그를 오인해
# 붙잡지 않게 하고(국소성), (2) 그래도 리젝될 땐 어떤 토큰을 gh 호출로 인식
# 했는지 사유에 노출해 오탐 자기진단 비용을 줄인다.
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|"})

# gh의 값-소비 전역 플래그 — subcommand(pr create·pr comment·pr merge) 앞에
# 올 수 있다(`gh --repo o/r pr comment ...`). 완결 목록이 아니다(상습범
# 목록 방식) — 새로 관측되면 추가한다.
_GH_GLOBAL_VALUE_FLAGS = frozenset({"--repo", "-R", "--hostname"})


def _find_gh_pr_span(argv: list[str], subcommand: str) -> tuple[int, int] | None:
    """`gh [전역플래그...] pr <subcommand>`의 (gh 토큰 인덱스, subcommand 토큰
    인덱스)를 찾는다. 복합 명령(`cd x && gh pr create ...`) 안에 있어도 잡는다.

    HIGH(선재 결함): 인접 3토큰 고정 매칭은 `gh --repo o/r pr create`처럼
    전역 플래그가 subcommand 앞에 오면 놓쳐 무검사로 샌다 — gh 뒤 첫 두
    non-flag 토큰(전역 플래그는 건너뜀) 방식으로 완화한다. create·merge·
    comment가 이 함수 하나를 공유하므로 셋 다 같이 고쳐진다.
    """
    n = len(argv)
    for i in range(n):
        if Path(argv[i]).name != "gh":
            continue
        j = i + 1
        while j < n and argv[j].startswith("-"):
            if argv[j] in _GH_GLOBAL_VALUE_FLAGS and j + 1 < n:
                j += 2
            else:
                j += 1
        if j + 1 < n and argv[j] == "pr" and argv[j + 1] == subcommand:
            return i, j + 1
    return None


def _segment_end(argv: list[str], start: int) -> int:
    """`start`부터 다음 셸 연산자 토큰(&&·||·;·|) 직전까지의 인덱스(exclusive).
    없으면 len(argv). --body/--body-file 탐색을 매칭된 gh 호출과 같은 셸
    문장 안으로만 좁힌다(국소성) — `&&`로 이어진 다음 명령의 플래그를 이
    호출 소속으로 오인하지 않는다."""
    for j in range(start, len(argv)):
        if argv[j] in _SHELL_OPERATORS:
            return j
    return len(argv)


def _match_diagnostic(argv: list[str], span: tuple[int, int], subcommand: str) -> str:
    """리젝 사유에 붙일 자기진단 힌트 — 어떤 토큰을 `gh pr <subcommand>`로
    인식했는지 위치·내용을 노출한다. 오탐(주석·heredoc 안 평문 등)이어도
    근본 해결이 불가능하니, 사람이 그 위치를 보고 즉시 오탐임을 판별하게
    하는 것으로 대신한다."""
    gh_i, subcmd_i = span
    return (
        f" [진단: 'gh ... pr {subcommand}'로 인식한 토큰 {gh_i}..{subcmd_i}="
        f"{argv[gh_i:subcmd_i + 1]!r} — shlex는 셸 문법을 모른다(주석·"
        f"heredoc·문자열 안 평문도 매칭될 수 있음). 오탐이면 그 주변 원문을 "
        f"의심하라.]"
    )


def _body_from_argv(argv: list[str], start: int = 0, end: int | None = None) -> tuple[str | None, str | None]:
    """`--body`/`--body-file` 플래그에서 본문을 뽑는다 — `gh pr create`와
    `gh pr comment`가 같은 플래그 계약을 쓰므로 공유한다. `[start, end)`
    범위로만 스캔한다(국소성) — 기본은 argv 전체.

    알려진 한계(정직 표기, fast-follow): `--body`가 중복되면 첫 값만 본다
    (gh 자체는 마지막 값이 유효할 수 있다). 아직 관측된 실사고가 아니다.

    반환: (body, reason_if_uninspectable). 호출자가 이미 대상 서브커맨드인지
    확인했다고 가정한다.
    """
    if end is None:
        end = len(argv)
    for i in range(start, end):
        tok = argv[i]
        if tok in _BODY_FLAGS and i + 1 < end:
            return argv[i + 1], None
        if tok.startswith("--body="):
            return tok.split("=", 1)[1], None
        if tok in _BODY_FILE_FLAGS and i + 1 < end:
            return _resolve_body_file(argv[i + 1])
        if tok.startswith("--body-file="):
            return _resolve_body_file(tok.split("=", 1)[1])

    # 알려진 한계(정직 표기, fast-follow): comment 호출도 이 문구를 그대로
    # 쓴다 — "--fill"은 create 전용 플래그라 comment엔 안 맞지만, 아직
    # 혼동 사례가 관측되지 않아 지금은 고치지 않는다.
    return None, "본문이 명령에 없음(--fill·에디터 대화형 등) — --body-file로 넘겨라"


def _body_from_match(argv: list[str], span: tuple[int, int], subcommand: str) -> tuple[str | None, str | None]:
    """매칭된 gh 호출(span) 소속 --body/--body-file만 찾는다(국소성) — 매칭된
    subcommand 토큰 뒤부터 다음 셸 연산자 전까지로 범위를 좁힌다. 실패하면
    사유에 매칭 위치를 붙인다(자기진단, CRITICAL 처방 2)."""
    _, subcmd_i = span
    start = subcmd_i + 1
    end = _segment_end(argv, start)
    body, reason = _body_from_argv(argv, start=start, end=end)
    if body is None and reason is not None:
        reason = reason + _match_diagnostic(argv, span, subcommand)
    return body, reason


def extract_body_from_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr create ...`에서 본문을 뽑는다.

    반환: (body, reason_if_uninspectable). gh 호출이 아니면 (None, None) —
    호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:  # 따옴표 안 닫힘 등 — 셸이 알아서 죽는다
        return None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, "create")
    if span is None:
        return None, None

    return _body_from_match(argv, span, "create")


def extract_body_from_comment_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr comment ...`에서 코멘트 본문을 뽑는다. `gh pr create`와 같은
    `--body`/`--body-file` 파싱을 재사용한다(둘 다 같은 플래그 계약).

    반환: (body, reason_if_uninspectable). gh pr comment 호출이 아니면
    (None, None) — 호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, "comment")
    if span is None:
        return None, None

    return _body_from_match(argv, span, "comment")


# --- gh pr create 제목 게이트(S5): conventional-commit -----------------------
#
# 제목은 create 전용 축이다 — merge는 이미 만들어진 PR을 가리킬 뿐 제목을 새로
# 짓지 않고(그 PR을 만든 create가 이미 검사받았다), comment는 애초에 제목이
# 없다. 그래서 body/comment/merge 어느 검사기와도 안 겹친다.

# 닫힌 집합이다 — EXEMPT_SECTIONS·JARGON_TERMS와 달리 저장소마다 다른 값이
# 아니라 conventional commit 표준 자체가 정의하는 타입이라 gate_config.py(레포별
# 설정)로 안 뽑는다. 새 타입이 필요하면 표준이 바뀐 것이므로 core를 고친다.
CONVENTIONAL_COMMIT_TYPES: tuple[str, ...] = (
    "feat", "fix", "docs", "chore", "refactor", "test", "perf", "build", "ci",
    "style", "revert",
)

# `type(scope): subject` 또는 `type: subject`(콜론 뒤 공백 하나 필수). type은
# 일단 대소문자 관계없이 뽑아 미지 타입 메시지에 그대로 보여준다 — "Fix" 같은
# 대소문자 오타를 "형식 위반"이 아니라 "타입 미지"로 알려줘야 저자가 뭘 고칠지
# 안다. 소문자 여부 자체는 CONVENTIONAL_COMMIT_TYPES 멤버십 검사가 가른다.
_TITLE_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^()]+)\))?:\s+(?P<subject>\S.*)$"
)


def check_pr_title(title: str) -> list[str]:
    """PR 제목이 닫힌 conventional-commit 타입 집합 + `type(scope)?: subject`
    형식을 따르는지 검사한다(빈 리스트 = 통과)."""
    m = _TITLE_RE.match(title.strip())
    if not m:
        return [
            f"PR 제목 형식 위반 — '{title}': 'type(scope): subject' 또는 "
            f"'type: subject' 형태여야 한다(콜론 뒤 공백 필요). 허용 타입: "
            f"{', '.join(CONVENTIONAL_COMMIT_TYPES)}."
        ]
    if m.group("type") not in CONVENTIONAL_COMMIT_TYPES:
        return [
            f"PR 제목 타입 '{m.group('type')}' 미지 — 허용 타입: "
            f"{', '.join(CONVENTIONAL_COMMIT_TYPES)}."
        ]
    return []


_TITLE_FLAGS = {"--title", "-t"}


def extract_title_from_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr create ...`에서 제목을 뽑는다 — `extract_body_from_command`의
    거울상(같은 `_find_gh_pr_span`·`_segment_end` 국소성 규약을 공유한다).
    `gh pr create`가 아니면 (None, None) — 호출자가 '검사 대상 아님'으로
    통과시킨다.

    **제목 플래그가 없어도 (None, None)이다(fail-open)** — body와 다른
    선택이다. body는 플래그가 없으면 리젝 사유를 낸다(우회 차단, 모듈
    docstring 참조). 하지만 이 게이트가 강제하는 축은 "제목이 있다면 형식이
    맞아야 한다"이지 "제목이 항상 있어야 한다"가 아니다 — `--fill` 등 제목이
    명령 인자에 없는 create 호출은 이미 body 부재로 fail-closed 리젝되므로
    (`run_hook`이 body를 먼저 확인한다), 여기서 제목 부재까지 리젝하면 같은
    호출을 두 번 막는 것 없이 새로 얻는 것도 없다.

    반환: (title, reason_if_uninspectable).
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, "create")
    if span is None:
        return None, None

    _, subcmd_i = span
    start = subcmd_i + 1
    end = _segment_end(argv, start)
    for i in range(start, end):
        tok = argv[i]
        if tok in _TITLE_FLAGS and i + 1 < end:
            return argv[i + 1], None
        if tok.startswith("--title="):
            return tok.split("=", 1)[1], None
    return None, None


def _report_title(violations: list[str], title: str) -> None:
    """PR 제목 위반을 stderr로 보고. `_report_comment`와 같은 골격(섹션 총계가
    없다 — 제목은 섹션이 없는 한 줄이다)."""
    print(
        f"[check_pr_body] PR 제목 리젝 — 위반 {len(violations)}건:",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  - {v}", file=sys.stderr)


# --- gh pr merge 게이트 ------------------------------------------------------
#
# "머지는 사용자 몫 — 감독·구현자는 머지하지 않는다"가 이미 규약이었으나 게이트가
# 0이었다 — 이 절이 그걸 처음 기계로 강제한다. `gh pr create`와 달리 본문이
# 명령 인자에 없다(머지 시점엔 이미 작성된 PR을 가리킬 뿐이므로) — `gh pr view
# --json body`로 능동 조회한다.

def _is_gh_pr_merge(argv: list[str]) -> bool:
    """`gh pr merge`가 복합 명령(`cd x && gh pr merge ...`) 안에 있어도 잡는다.
    `_find_gh_pr_span`을 재사용 — create·comment와 같은 전역 플래그 완화를
    받는다(HIGH-2, 선재 결함: `gh --repo o/r pr merge`도 이제 잡힌다)."""
    return _find_gh_pr_span(argv, "merge") is not None


# gh pr merge의 값-소비 플래그 — 이 값 토큰을 PR 식별자로 오인하면 안 된다
# (예: `gh pr merge --subject "메시지"`에서 "메시지"는 식별자가 아니다).
_MERGE_VALUE_FLAGS = {"--subject", "-t", "--body", "-b", "--body-file",
                       "-F", "--match-head-commit"}


def _merge_target(argv: list[str]) -> str | None:
    """`gh pr merge [<번호|브랜치|URL>] [옵션...]`에서 대상 식별자를 뽑는다.
    옵션이 아닌 첫 토큰이 식별자다 — 단, `--subject`/`--body` 같은 값-소비
    플래그의 값 토큰은 건너뛴다(안 그러면 그 값을 식별자로 오인해 정상 머지를
    오탐 리젝한다). 식별자가 생략되면(gh가 현재 브랜치를 추론) None."""
    span = _find_gh_pr_span(argv, "merge")
    if span is None:
        return None
    _, subcmd_i = span
    skip_next = False
    for tok in argv[subcmd_i + 1:]:
        if skip_next:
            skip_next = False
            continue
        if tok in _MERGE_VALUE_FLAGS:
            skip_next = True
            continue
        if tok.startswith("--") and "=" in tok:
            continue  # --subject=foo 형태 — 값이 토큰에 붙어 있다
        if not tok.startswith("-"):
            return tok
    return None


def _fetch_pr_body(identifier: str | None) -> tuple[dict | None, str | None]:
    """`gh pr view [<식별자>] --json body,comments,headRefOid`로 대상 PR의
    스냅샷을 한 번에 조회한다.

    이름은 그대로지만(호출자 다수가 이미 이 이름을 쓴다) 반환값은 본문 문자열이
    아니라 dict다(`body`·`comments`·`headRefOid` 키) — `--merge-check`가
    체크리스트뿐 아니라 리뷰 종합 코멘트·현재 head SHA까지 필요해서 조회를
    확장했다. **subprocess 호출은 이 함수 하나뿐이다** — merge 훅·comment 백스톱·
    `--merge-check`가 이 조회 하나를 공유한다(중복 `gh pr view` 금지).

    반환: (data, reason_if_unreadable). 조회 자체가 실패하면(gh 미설치·인증 안
    됨·PR 번호 틀림 등) 본문을 못 들여다본 것과 같으므로 fail-closed로 취급한다
    (검사 우회 금지와 같은 원칙 — 못 보면 통과가 아니라 리젝).
    """
    cmd = ["gh", "pr", "view"]
    if identifier is not None:
        cmd.append(identifier)
    cmd += ["--json", "body,comments,headRefOid"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:  # gh 자체가 없음 등
        return None, f"gh pr view 실행 실패({e})"
    if result.returncode != 0:
        stderr = result.stderr.strip() or f"exit {result.returncode}"
        return None, f"gh pr view 실패 — 본문을 못 들여다봄({stderr})"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return None, f"gh pr view 응답 파싱 실패({e})"
    if not data.get("body"):
        return None, "gh pr view 응답에 본문이 없거나 비어 있음"
    return data, None


def check_review_evidence(comments: list[dict], head_sha: str) -> list[str]:
    """리뷰 종합 코멘트의 존재·신선도를 검사한다("근거 없는 체크 금지"를 처음
    기계로 태우는 백스톱 — 이 원칙에 해당 규칙 문서가 있는 저장소는
    `gate_config.RULE_REVIEW_EVIDENCE`로 조문을 인용한다).

    1. `<헤더 접두어> — <차수> (<SHA>)` 형식 헤더 코멘트가 하나 이상 있어야 한다.
    2. 그중 최신(코멘트 목록에서 가장 뒤에 매치된) 것의 SHA가 `head_sha`로
       시작해야 한다 — 헤더의 SHA는 축약형(`8c8f4f7`)이고 `head_sha`는 전체
       SHA(`headRefOid`)라 접두어 비교로 잰다. 안 맞으면 옛 코멘트로 영구통과
       하는 걸 막는다(PR에 새 커밋이 얹혔는데 리뷰 종합은 그 이전 커밋 기준).

    헤더 접두어를 여기 하드코딩하지 않는다 — `load_review_header_prefix`가
    `docs_format/pr-comment.md`에서 뽑는다. 못 뽑으면 잴 자가 없어서
    fail-closed로 리젝한다(check_comment의 예산 미검출과 같은 처방).
    """
    prefix = load_review_header_prefix()
    if prefix is None:
        return [
            f"리뷰 종합 헤더 포맷을 못 뽑음({_COMMENT_FORM_PATH}) — 위반이 없어서 "
            f"통과가 아니라 잴 자가 없어서 통과할 뻔한 것이다. 폼 파일의 예시 "
            f"문구를 확인하라(fail-closed)."
        ]
    pattern = _review_header_pattern(prefix)
    matches = [
        m
        for c in comments
        for line in (c.get("body") or "").splitlines()
        if (m := pattern.match(line.strip()))
    ]
    if not matches:
        cite = _rule_cite(RULE_REVIEW_EVIDENCE, "제1조")
        return [
            f"리뷰 종합 코멘트 없음 — '{prefix} — <차수> (<SHA>)' 형식 헤더 "
            f"코멘트가 최소 1개 있어야 한다{cite}."
        ]
    comment_sha = matches[-1].group("sha")
    if not head_sha or not head_sha.lower().startswith(comment_sha.lower()):
        cite = _rule_cite(RULE_REVIEW_EVIDENCE, "제5조 — 판정마다 새 코멘트")
        return [
            f"리뷰 근거가 낡음 — 최신 코멘트 SHA {comment_sha} != 현재 head "
            f"{head_sha or '(없음)'} — 리뷰 뒤 커밋이 더 얹혔다. 새 리뷰 종합 "
            f"코멘트를 달아라{cite}."
        ]
    return []


def extract_pr_view_from_merge_command(command: str) -> tuple[dict | None, str | None]:
    """`gh pr merge ...`가 리젝 대상인 PR의 스냅샷(body·comments·headRefOid)을
    `gh pr view`로 한 번에 조회해 뽑는다 — merge 훅과 `--merge-check`가 이 조회
    하나를 공유한다(단일 콜).

    반환: (data, reason_if_uninspectable). gh pr merge 호출이 아니면 (None, None)
    — 호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return None, f"명령 파싱 실패({e})"

    if not _is_gh_pr_merge(argv):
        return None, None

    identifier = _merge_target(argv)
    return _fetch_pr_body(identifier)


def extract_body_from_merge_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr merge ...`가 리젝 대상인 PR의 본문만 뽑는다(기존 계약 유지).

    `extract_pr_view_from_merge_command`를 재사용해 스냅샷에서 본문만 꺼낸다 —
    argv 파싱·merge 감지 로직을 재구현하지 않는다.
    """
    data, reason = extract_pr_view_from_merge_command(command)
    if data is None:
        return None, reason
    return data["body"], None


def check_merge_readiness(identifier: str | None) -> list[str]:
    """`--merge-check` dry-run 판정 — **실제 머지(`gh pr merge`)는 하지 않는다.**

    전부 통과해야 "머지 가능"이다:
      1. PR 본문 예산 섹션 + 확인 체크리스트 전량 체크(`check_pr_body`를 merge와
         같은 기준으로 재사용 — `require_checklist_complete=True`).
      2·3. 리뷰 종합 코멘트의 존재·신선도(`check_review_evidence` — `gh pr
         merge` 훅 백스톱과 같은 검사기를 공유한다).
    """
    data, reason = _fetch_pr_body(identifier)
    if data is None:
        return [reason or "PR 조회 실패(gh pr view)"]
    violations = check_pr_body(data["body"], require_checklist_complete=True)
    violations.extend(
        check_review_evidence(data.get("comments") or [], data.get("headRefOid") or "")
    )
    return violations


def run_hook() -> int:
    """Claude Code PreToolUse 훅. stdin=훅 JSON. exit 2 = 툴 호출 리젝."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"[check_pr_body] 훅 payload 파싱 실패: {e}", file=sys.stderr)
        return 1  # 논블로킹 — 훅 자체 고장으로 작업을 막지는 않는다

    command = (payload.get("tool_input") or {}).get("command", "")
    body, reason = extract_body_from_command(command)
    # create = 리뷰 요청 시점이라 체크리스트 완료를 요구하지 않는다(형식만).
    # merge = 리뷰 끝난 뒤라 체크리스트 전량 + 리뷰 종합 코멘트 존재·신선도까지
    # 요구한다(백스톱, check_review_evidence).
    # comment = PR 본문이 아니라 근거 기록 — 섹션·체크리스트 없이 분량·문장·
    # 용어 풀이만 강제한다(check_comment).
    is_merge = False
    is_comment = False
    merge_view: dict | None = None
    if body is None and reason is None:
        # gh pr create가 아님 — gh pr merge인지 본다.
        merge_view, reason = extract_pr_view_from_merge_command(command)
        is_merge = True
        if merge_view is not None:
            body = merge_view["body"]
    if body is None and reason is None:
        # gh pr merge도 아님 — gh pr comment인지 본다(셋 다 아니면 통과).
        body, reason = extract_body_from_comment_command(command)
        is_merge = False
        is_comment = True

    if body is None:
        if reason is None:
            return 0  # gh pr create·merge·comment 어느 것도 아님 — 검사 대상 아님
        print(f"[check_pr_body] PR 본문 리젝 — {reason}", file=sys.stderr)
        return 2

    if is_comment:
        violations = check_comment(body)
        if violations:
            _report_comment(violations, body)
            return 2
        return 0

    if not is_merge:
        # create만 — 제목 conventional-commit 게이트(S5). merge는 이미 만들어진
        # PR을 가리킬 뿐 제목을 새로 짓지 않으므로 검사 대상이 아니다.
        title, _ = extract_title_from_command(command)
        if title is not None:
            title_violations = check_pr_title(title)
            if title_violations:
                _report_title(title_violations, title)
                return 2

    violations = check_pr_body(body, require_checklist_complete=is_merge)
    if is_merge and merge_view is not None:
        # 백스톱: 체크리스트가 전량 체크돼도 리뷰 종합 코멘트가 없거나 낡았으면
        # 여전히 리젝한다(check_review_evidence를 훅이 처음 강제).
        violations = violations + check_review_evidence(
            merge_view.get("comments") or [], merge_view.get("headRefOid") or ""
        )
    if violations:
        _report(violations, body)
        return 2
    return 0


def run_merge_check(identifier: str) -> int:
    """`--merge-check` dry-run 진입점 — **`gh pr merge`를 부르지 않는다.**
    `check_merge_readiness`의 판정을 사람이 읽을 출력으로 옮길 뿐이다."""
    violations = check_merge_readiness(identifier)
    if violations:
        print(
            f"[check_pr_body] 머지 준비 안 됨 — 위반 {len(violations)}건:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("[check_pr_body] 리뷰 근거 확인됨 — 사용자 승인/머지 가능")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="PR 본문 구조·분량 게이트")
    ap.add_argument("--body-file", type=Path, help="검사할 PR 본문 파일")
    ap.add_argument("--hook", action="store_true",
                    help="Claude Code PreToolUse 훅 모드(stdin=훅 JSON)")
    ap.add_argument("--merge-check", metavar="PR",
                    help="머지 준비 dry-run 검사(실제 머지 안 함) — 대상 PR 번호·브랜치·URL")
    args = ap.parse_args(argv)

    if args.hook:
        return run_hook()
    if args.merge_check is not None:
        return run_merge_check(args.merge_check)
    if not args.body_file:
        ap.error("--body-file 또는 --hook 또는 --merge-check 중 하나가 필요하다")

    body = args.body_file.read_text(encoding="utf-8")
    violations = check_pr_body(body)
    if violations:
        _report(violations, body)
        return 1
    print(f"[check_pr_body] 통과 — {args.body_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
