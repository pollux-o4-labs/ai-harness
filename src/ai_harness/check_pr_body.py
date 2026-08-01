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
아직 체크를 못 했다 — 형식(섹션·분량·문장·제목)만 강제하고 확인 절은 '존재'만
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
  ai-harness check-pr --merge-check <PR> --repo <owner/repo>
                                            # 대상 저장소 명시(생략 시 현재
                                            # 디렉터리 remote로 추론)

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
구조는 그대로 강제한다(`docs_format/pr-comment.md`의 줄수·줄자수 예산).

  gh pr create    섹션·예산·체크절(존재만)·제목(conventional-commit)
  gh pr merge     위 + 체크 전량(제목은 이미 만들어진 PR을 가리킬 뿐이라 검사 안 함)
  gh pr comment   줄자수·줄수 예산 + 한 줄 한 문장(섹션·체크리스트 없음)
                  + 리뷰 종합이면 직전 종합과 본문이 같은지(check_review_repeat)

(comment 예산 수치는 `docs_format/pr-comment.md`가 정본 — 여기 재서술 안 함.)

**레포별 설정은 `gate_config.py`에 있다** — 면제 섹션·규칙 인용처럼
저장소마다 달라야 하는 값은 이 core에 안 둔다. core는 설치된 패키지 하나가
정본이고, 대상 저장소는 자기 `gate_config.py`만 두면 CLI가 그 값을 얹는다.
"""
from __future__ import annotations

import enum
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# 레포별 설정(면제 섹션·규칙 인용) — 대상 저장소가 값을 오버레이한다.
from ai_harness.gate_config import (
    EXEMPT_SECTIONS,
    RULE_REVIEW_EVIDENCE,
    build_exempt_shape,
    rule_cite as _rule_cite,
)
# gh 명령 문자열에서 본문·제목·머지 대상·저장소 값을 뽑는 파싱(gh 문법)은
# gh_command.py가 진다 — 이 파일은 그 값으로 판정만 한다(층 구분은
# gh_command.py 모듈 docstring 참고).
from ai_harness.gh_command import (
    extract_body_from_comment_command,
    extract_body_from_command,
    extract_title_from_command,
    resolve_comment_call,
    resolve_merge_call,
)
# 체크리스트 섹션명은 이 파일 로직이 직접 쓰고, 테스트도 `cpb.CHECKLIST_SECTION`
# 으로 읽는다. `is_issue_ref_line`·`is_checkbox_line`은 여기서 재노출하지
# 않는다 — 쓰는 쪽이 gate_config 하나뿐이라 그쪽이 line_shapes에서 바로
# 쓰면 된다. 아래 넷(펜스·문장 경계·예산 파싱)은 이 파일 자기 로직이
# 직접 소비하므로 그대로 쓴다.
from ai_harness.line_shapes import (
    CHECKLIST_SECTION,
    LINE_CHARS_PATTERN,
    MAX_LINES_PATTERN,
    extract_budgets,
    has_sentence_boundary,
    is_fence_line,
)

# 이 dict가 PR 본문 예산의 정본이다 — 문서·템플릿은 이 값을 재서술하지 말고
# 이 파일을 가리킬 것. 위반 메시지가 실측값과 함께 예산을 알려주므로 저자는
# 여기를 안 읽어도 된다.
SECTION_BUDGETS: dict[str, int] = {
    "요약": 150,
    "변경": 300,
    "범위 밖": 100,
    "검증": 150,
}

_NONE_LINE = re.compile(r"^\s*(?:없음|N/?A)\s*$", re.IGNORECASE)

_EXEMPT_SHAPE = build_exempt_shape()


# 문장 경계 판정(has_sentence_boundary)의 정본·한계·재판정 트리거는
# line_shapes.py — check_doc_form.py와 이 파일이 같은 "한 줄 한 문장" 규칙을
# 그 정본 하나로 공유한다.
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
    # 이어지는 항목들은 org 공용 템플릿의 체크리스트에서 왔다 — 우리 목록이 문서 정합에만
    # 쏠려 있어 코드 변경의 자기신고 축(테스트·호환성)이 비어 있었다. 나머지 org
    # 항목(self-review·관련 문서 갱신)은 위 항목과 겹쳐 옮기지 않았다(재서술 금지).
    "필요한 테스트를 추가하거나 갱신했다",
    "동작을 깨는 변경(breaking change)이라면 본문에 명시했다",
)

# `gh pr comment` 예산의 정본 — 이 dict는 이 파일에 없다. 문구 관례 파싱
# 정규식은 check_doc_form.py의 `_BUDGET_PATS`와 line_shapes.py의 공유 정본을
# 함께 쓴다(키 집합과 폼 파일 경로만 이 파일이 따로 갖는다). 폼 파일이 없으면
# 코멘트 게이트·리뷰 근거 검사가 fail-closed로 리젝한다(우회가 아니라 "아직
# 안 채운 설정"임을 알리는 것) — 저장소가 이 경로에 폼 파일을 작성하면
# 그때부터 켜진다.
_COMMENT_FORM_PATH = (
    Path(__file__).resolve().parent / "docs_format" / "pr-comment.md"
)
_COMMENT_BUDGET_PATS = {
    "line_chars": LINE_CHARS_PATTERN,
    "max_lines": MAX_LINES_PATTERN,
}

# 리뷰 종합 코멘트 헤더 접두어("## 리뷰 종합") — pr-comment.md의 예시 문구
# (`## 리뷰 종합 — 2차 (8c8f4f7)`)에서 뽑는다. 헤더 관례가 바뀌면 폼 파일만
# 고치면 되고 이 스크립트는 안 건드린다.
_REVIEW_HEADER_EXAMPLE = re.compile(r"`(##\s+.+?)\s*—\s*\d+차\s*\([0-9a-fA-F]+\)`")

# 리뷰 종합 코멘트 골격 선언 — pr-comment.md(core 번들)가 정본. 필수 `##`
# 섹션·닫힌 등급 라벨을 예산·헤더와 같은 관례로 파싱한다. 선언이 없으면 골격
# 강제는 no-op(저장소별 토글 아님 — 구버전 폼일 때만) — load_review_skeleton·
# check_review_skeleton 참조.
_REVIEW_SECTIONS_PAT = re.compile(r"필수 `##` 섹션:\s*(.+?)\.")
_REVIEW_LABELS_PAT = re.compile(r"등급 라벨\(닫힌 집합\):\s*(.+?)\.")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_H2 = re.compile(r"^##\s+(.+?)\s*$")
# 펜스 블록을 통째로 벗겨내는 전체 텍스트 치환 — 줄 단위 토글인
# `is_fence_line`과 매칭 단위가 달라 그 함수로 대체하지 못한다(이쪽은 여는
# 펜스와 닫는 펜스의 짝을 정규식 하나로 찾는다). 다만 백틱·틸드 둘 다 받아야
# 하는 것은 같다 — 한쪽만 알면 같은 문서가 코멘트로는 통과하고 본문으로는
# 리젝된다. `is_fence_line`과 같은 수준이며 펜스 길이 일치는 검사하지 않는다.
_FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
# 코멘트 줄 검사용 펜스 토글은 is_fence_line(line_shapes.py)을 쓴다 — 정본·
# 한계는 그쪽 참고.
_CHECKED_ITEM = re.compile(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$")


def strip_html_comments(text: str) -> str:
    """템플릿 힌트 주석을 제거 — 힌트는 예산을 먹지 않고, 남겨둬도 본문이 아니다."""
    return _HTML_COMMENT.sub("", text)


def measure(text: str) -> int:
    """섹션 분량(글자수). 공백은 연속 1칸으로 정규화해 줄바꿈 들여쓰기가 예산을
    먹지 않게 한다 — 재는 대상은 저자가 쓴 내용이지 레이아웃이 아니다."""
    return len(" ".join(text.split()))


def strip_code(text: str) -> str:
    """코드펜스·인라인코드 제거 — 판정 대상은 산문이지 명령어가 아니다.
    (분량 예산은 반대로 코드까지 센다 — 로그를 붙일 자리가 아니라 명령+종료코드
    자리이므로 예산 안에 들어와야 한다.)"""
    return _INLINE_CODE.sub("", _FENCED_CODE.sub("", text))


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
            if has_sentence_boundary(line):
                violations.append(
                    f"섹션 '## {name}' {i}번째 줄에 문장이 여럿 — "
                    f"문장마다 줄바꿈해 불릿로 빼라(마침표·물음표·느낌표 뒤에서 끊는다)."
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
        # 섹션이 비어 보이고 그대로 통과한다(자가 공격으로 실측한 우회구). 문장
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
    시점은 True로 전량 체크를 요구한다(리뷰 끝난 뒤). 형식(섹션·분량·문장)은
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
    return violations


# --- gh pr comment 게이트 ----------------------------------------------------
#
# 코멘트는 PR 본문이 아니라 리뷰 항목별 근거 기록이다 — 섹션 골격·체크리스트는
# 적용하지 않는다. 단, 그 코멘트도 나중에 읽어야 할 문서가 되므로 분량·문장
# 구조는 그대로 강제한다. 내부 용어가 과한지는 리뷰어가 본다(규칙 01 제3조).

def _read_comment_form_text() -> str | None:
    """코멘트 폼(pr-comment.md, core 번들) 텍스트 — 없으면 None. 예산·헤더·골격
    로더가 공유하는 단일 읽기 지점(파일읽기 3중 복붙 제거)."""
    if not _COMMENT_FORM_PATH.is_file():
        return None
    return _COMMENT_FORM_PATH.read_text(encoding="utf-8")


def load_comment_budgets() -> dict[str, int]:
    """`docs_format/pr-comment.md`에서 코멘트 예산을 뽑는다.

    폼이 정본이라 수치를 여기 하드코딩하지 않는다. 못 뽑으면 빈 dict를
    반환한다 — fail-closed 판단은 check_comment가 한다.
    """
    text = _read_comment_form_text()
    if text is None:
        return {}
    return extract_budgets(text, _COMMENT_BUDGET_PATS)


def load_review_header_prefix() -> str | None:
    """`docs_format/pr-comment.md`의 예시 문구에서 리뷰 종합 헤더 접두어를
    뽑는다(`"## 리뷰 종합 — 2차 (8c8f4f7)"` → `"## 리뷰 종합"`).

    load_comment_budgets와 같은 이유로 토큰을 이 파일에 재서술하지 않는다.
    못 뽑으면 None — fail-closed 판단은 호출자(check_review_evidence)가 한다.
    """
    text = _read_comment_form_text()
    if text is None:
        return None
    m = _REVIEW_HEADER_EXAMPLE.search(text)
    return m.group(1).strip() if m else None


def load_review_skeleton() -> tuple[list[str], list[str]]:
    """`docs_format/pr-comment.md`에서 리뷰 종합 코멘트의 필수 `##` 섹션과 닫힌
    등급 라벨을 뽑는다(폼이 정본, 예산·헤더와 같은 파싱 관례).

    반환: (required_sections, verdict_labels). 폼이 선언을 안 했으면 각각 빈
    리스트라 check_review_skeleton이 no-op이 된다. 폼은 전 레포 공통 core라
    이건 저장소별 토글이 아니라 '선언을 아직 안 넣은 폼(구버전)'일 때만
    발동한다. 예산의 fail-closed와 다른 이유: 예산은 '잴 자가 없음'이라 리젝
    하지만, 골격 미선언은 '이 검사를 아직 안 켠 것'이라 통과가 맞다(원칙 5)."""
    text = _read_comment_form_text()
    if text is None:
        return [], []
    sm = _REVIEW_SECTIONS_PAT.search(text)
    lm = _REVIEW_LABELS_PAT.search(text)
    sections = [s.strip() for s in sm.group(1).split(",")] if sm else []
    labels = [s.strip() for s in lm.group(1).split(",")] if lm else []
    return sections, labels


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
    문장)뿐이다 — 내부 용어 판정은 리뷰어 몫이다(규칙 01 제3조). **닫힌**
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
    fence_lines = [i for i, line in enumerate(lines, 1) if is_fence_line(line)]
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
        if has_sentence_boundary(line):
            violations.append(
                f"코멘트 {i}번째 줄에 문장이 여럿 — 문장마다 줄바꿈해 불릿로 "
                f"빼라(마침표·물음표·느낌표 뒤에서 끊는다)."
            )
        if line_max is not None and len(line) > line_max:
            violations.append(
                f"코멘트 {i}번째 줄 {len(line)}자 > {line_max}자 — 한 줄에 "
                f"흐름을 우겨넣지 말고 함축해라(문맥이 이어지면 문맥 단위로 나눈다)."
            )

    # 리뷰 종합 코멘트면 폼 골격(필수 섹션·등급 라벨)까지 강제한다 — 일반
    # 코멘트엔 no-op. 존재·신선도는 check_review_evidence(머지), 골격은 여기(게시).
    violations.extend(check_review_skeleton(body))
    return violations


def check_review_skeleton(body: str) -> list[str]:
    """리뷰 종합 코멘트(`## 리뷰 종합` 헤더를 단 코멘트)가 폼이 선언한 골격을
    갖췄는지 검사한다 — 필수 `##` 섹션 전부 + 등급 라벨 최소 하나.

    리뷰 종합 코멘트가 아니면(헤더 없음) 빈 리스트 — 일반 코멘트는 골격 대상이
    아니다. 미달이면 리젝 사유와 함께 채울 골격 템플릿을 낸다("안 쓰면 쓰게").
    라벨의 진실성(등급이 옳은가)은 못 밝힌다 — 그건 리뷰어 몫(원칙 2), 여기선
    형식(있나)만 강제한다.
    """
    prefix = load_review_header_prefix()
    if prefix is None:
        return []  # 헤더 접두어 못 뽑음 — check_comment 예산 경로가 이미 fail-closed
    if not any(line.strip().startswith(prefix) for line in body.splitlines()):
        return []  # 리뷰 종합 코멘트 아님 → 골격 대상 아님
    required, labels = load_review_skeleton()
    if not required and not labels:
        return []  # 폼이 골격 강제를 안 켬(선언 없음)
    present = {m.group(1) for line in body.splitlines() if (m := _H2.match(line))}
    violations: list[str] = []
    for sec in required:
        if not any(sec in h for h in present):
            violations.append(f"리뷰 종합 코멘트에 `## {sec}` 섹션 없음 — 골격 미달.")
    # 단어경계로 본다 — 부분문자열이면 "OK"가 "TOKEN"에, "NIT"가 "UNIT"에
    # 우연히 매칭돼 라벨 강제가 흔한 차용어 하나로 무력화된다(리뷰 지적).
    if labels and not any(
        re.search(rf"\b{re.escape(lbl)}\b", body) for lbl in labels
    ):
        violations.append(
            f"리뷰 종합 코멘트에 등급 라벨 없음 — {' / '.join(labels)} 중 최소 "
            f"하나로 각 항목을 매겨라."
        )
    if violations:
        violations.append(_review_skeleton_template(prefix, required, labels))
    return violations


def _review_skeleton_template(prefix: str, sections: list[str], labels: list[str]) -> str:
    """리젝 시 건네는, 이대로 채우면 통과하는 골격 — 선언에서 생성한다(별도
    템플릿 파일 없이 단일 정본에서 파생, 드리프트 원천 차단)."""
    skel = [f"{prefix} — <차수> (<SHA>)"]
    for sec in sections:
        if sec in prefix:  # '리뷰 종합'은 헤더 줄이 이미 담는다
            continue
        skel.append(f"## {sec}")
    return (
        "골격 템플릿(이대로 채워라):\n"
        + "\n".join(skel)
        + f"\n등급 라벨: {' / '.join(labels)}"
    )


def _review_body_tail(pattern: re.Pattern[str], text: str) -> str | None:
    """리뷰 종합 코멘트에서 **헤더 줄을 뺀 나머지**를 낸다 — 종합이 아니면 None.

    헤더만 빼는 이유는 그 줄이 차수·SHA를 담아 매번 달라지는 유일한 줄이라서다.
    나머지가 같다는 것은 판정 내용이 한 글자도 안 바뀌었다는 뜻이다."""
    lines = text.splitlines()
    if not any(pattern.match(line.strip()) for line in lines):
        return None
    rest = [line for line in lines if not pattern.match(line.strip())]
    return "\n".join(rest).strip()


def check_review_repeat(body: str, comments: list[dict]) -> list[str]:
    """올리려는 리뷰 종합이 직전 종합과 헤더 줄만 빼고 같으면 리젝한다.

    `check_review_evidence`가 "리뷰 근거가 낡음"으로 반려할 때 그 요구는
    **재판정**이다. 그런데 헤더 SHA만 갈아끼워 같은 본문을 다시 올리면 그
    반려가 통과로 바뀐다(실사고: `sed -i 's/(0b56be0)/(36c867f)/'` 한 줄로
    통과시켰고 사람이 나중에 발견했다). 읽는 쪽은 새 head를 판정했다고 읽지만
    근거는 옛 시점 산출물이다 — 그 틈을 여기서 막는다.

    잴 수 있는 것만 잰다. "실제로 재현검증했는가"는 못 밝힌다(원칙 2 — 리뷰어
    몫). 여기선 **본문이 직전과 글자 그대로 같은가**만 본다. 한 줄이라도 새로
    쓰려면 그 사이 얹힌 커밋을 봐야 하고, 보면 판정이 따라온다. 아무 문장이나
    덧붙여 우회하는 것은 막지 못한다 — 게이트는 lint이며, 막으려는 것은 의식적
    우회가 아니라 무의식적 되풀이다.

    리뷰 종합이 아니거나(일반 코멘트) 직전 종합이 없으면(첫 판정) 빈 리스트.
    """
    prefix = load_review_header_prefix()
    if prefix is None:
        return []  # 헤더 접두어 못 뽑음 — check_comment 예산 경로가 이미 fail-closed
    pattern = _review_header_pattern(prefix)
    new_tail = _review_body_tail(pattern, body)
    if new_tail is None:
        return []  # 리뷰 종합 아님 → 대조 대상 아님
    prev_tail = None
    for c in comments:  # 목록 순서상 뒤가 최신 — 마지막 종합이 직전 판정이다
        tail = _review_body_tail(pattern, c.get("body") or "")
        if tail is not None:
            prev_tail = tail
    if prev_tail is None or prev_tail != new_tail:
        return []
    return [
        "직전 리뷰 종합과 본문이 같다 — 헤더 SHA만 바꾼 재게시는 재판정이 "
        "아니다. 그 사이 얹힌 커밋이 무엇이며 앞 판정이 유지되는지 써라"
        "(`git log --oneline <직전SHA>..<현재head>`). 바뀐 것이 없다는 판정도 "
        "쓸 내용이다."
    ]


def _print_violations(header: str, violations: list[str]) -> None:
    """헤더 한 줄 + 위반 목록(`  - {v}`)을 stderr로 찍는 공통 관용구.

    `_report`·`_report_comment`·`_report_title` 셋이 이 겉틀을 각자 되풀이하고
    있었다 — 헤더 문구·뒤따르는 힌트(있는 경우)만 호출부가 조립한다. 출력
    문자열 자체는 한 글자도 바뀌지 않는다(테스트가 메시지를 문자열로 검사).
    """
    print(header, file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)


def _report_comment(violations: list[str], body: str) -> None:
    """코멘트 위반을 stderr로 보고. PR 본문 `_report`와 달리 섹션 총계가 없다
    — 코멘트는 섹션이 없는 자유 형식이다."""
    _print_violations(
        f"[check_pr_body] PR 코멘트 리젝 — 위반 {len(violations)}건:", violations
    )
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
    _print_violations(
        f"[check_pr_body] PR 본문 리젝 — 위반 {len(violations)}건 "
        f"(총 {total}자 / 예산 {sum(SECTION_BUDGETS.values())}자):",
        violations,
    )
    print(
        # 처방은 실재하는 것만 가리킨다 — 없는 문서로 보내면 저자는 고칠 길을 잃고
        # 게이트를 지운다. 섹션·예산의 정본은 이 스크립트이므로 템플릿만 가리킨다.
        "\n형식: .github/PULL_REQUEST_TEMPLATE.md (섹션·예산·형태의 정본은 이 스크립트)",
        file=sys.stderr,
    )


# --- 훅 모드 ---------------------------------------------------------------
#
# 명령 문자열에서 본문·제목·머지 대상·저장소 값을 뽑는 파싱(gh 문법)은
# `gh_command.py`가 진다(위 import) — 이 파일은 그 값으로 판정만 한다.


# --- gh pr create 제목 게이트(S5): conventional-commit -----------------------
#
# 제목은 create 전용 축이다 — merge는 이미 만들어진 PR을 가리킬 뿐 제목을 새로
# 짓지 않고(그 PR을 만든 create가 이미 검사받았다), comment는 애초에 제목이
# 없다. 그래서 body/comment/merge 어느 검사기와도 안 겹친다.

# 닫힌 집합이다 — EXEMPT_SECTIONS와 달리 저장소마다 다른 값이
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


def _report_title(violations: list[str], title: str) -> None:
    """PR 제목 위반을 stderr로 보고. `_report_comment`와 같은 골격(섹션 총계가
    없다 — 제목은 섹션이 없는 한 줄이다)."""
    _print_violations(
        f"[check_pr_body] PR 제목 리젝 — 위반 {len(violations)}건:", violations
    )


# --- gh pr merge 게이트 ------------------------------------------------------
#
# "머지는 사용자 몫 — 감독·구현자는 머지하지 않는다"가 이미 규약이었으나 게이트가
# 0이었다 — 이 절이 그걸 처음 기계로 강제한다. `gh pr create`와 달리 본문이
# 명령 인자에 없다(머지 시점엔 이미 작성된 PR을 가리킬 뿐이므로) — `gh pr view
# --json body`로 능동 조회한다. 명령에서 대상 식별자·저장소를 뽑는 파싱은
# `gh_command.resolve_merge_call`이 진다 — 이 절은 그 값으로 조회·판정만 한다.


def _fetch_pr_body(identifier: str | None, repo: str | None = None) -> tuple[dict | None, str | None]:
    """`gh pr view [<식별자>] [--repo <저장소>] --json body,comments,headRefOid`로
    대상 PR의 스냅샷을 한 번에 조회한다.

    이름은 그대로지만(호출자 다수가 이미 이 이름을 쓴다) 반환값은 본문 문자열이
    아니라 dict다(`body`·`comments`·`headRefOid` 키) — `--merge-check`가
    체크리스트뿐 아니라 리뷰 종합 코멘트·현재 head SHA까지 필요해서 조회를
    확장했다. **subprocess 호출은 이 함수 하나뿐이다** — merge 훅·comment 백스톱·
    `--merge-check`가 이 조회 하나를 공유한다(중복 `gh pr view` 금지).

    `repo`(`owner/repo`)를 안 주면 gh가 현재 디렉터리의 remote로 저장소를
    추론한다 — 훅은 호출자의 작업 디렉터리가 아니라 세션 기준 디렉터리에서 돌아
    이 추론이 틀릴 수 있다(실사고: 다른 저장소의 같은 번호 PR을 조회해 오판).
    `gh pr merge --repo o/r ...`처럼 호출부가 저장소를 명시했으면 그 값을
    그대로 넘겨받아 조회를 그 저장소로 고정한다.

    반환: (data, reason_if_unreadable). 조회 자체가 실패하면(gh 미설치·인증 안
    됨·PR 번호 틀림 등) 본문을 못 들여다본 것과 같으므로 fail-closed로 취급한다
    (검사 우회 금지와 같은 원칙 — 못 보면 통과가 아니라 리젝).
    """
    cmd = ["gh", "pr", "view"]
    if identifier is not None:
        cmd.append(identifier)
    if repo is not None:
        cmd += ["--repo", repo]
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

    대상 식별자·저장소 파싱은 `gh_command.resolve_merge_call`에 위임한다 —
    이 함수는 그 값으로 조회 하나만 잇는다. 명령에 `--repo`/`-R`이 있으면 그
    값이 그대로 조회에 실린다(HIGH-3, 선재 결함: 훅이 세션 기준 디렉터리에서
    돌아 여러 저장소를 오가는 세션에서는 저장소 지정 없이 조회하면 엉뚱한
    저장소의 같은 번호 PR을 리젝했다).

    반환: (data, reason_if_uninspectable). gh pr merge 호출이 아니면 (None, None)
    — 호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    is_merge, identifier, repo, reason = resolve_merge_call(command)
    if reason is not None:
        return None, reason
    if not is_merge:
        return None, None
    return _fetch_pr_body(identifier, repo)


def check_merge_readiness(identifier: str | None, repo: str | None = None) -> list[str]:
    """`--merge-check` dry-run 판정 — **실제 머지(`gh pr merge`)는 하지 않는다.**

    전부 통과해야 "머지 가능"이다:
      1. PR 본문 예산 섹션 + 확인 체크리스트 전량 체크(`check_pr_body`를 merge와
         같은 기준으로 재사용 — `require_checklist_complete=True`).
      2·3. 리뷰 종합 코멘트의 존재·신선도(`check_review_evidence` — `gh pr
         merge` 훅 백스톱과 같은 검사기를 공유한다).

    `repo`는 `_fetch_pr_body`로 그대로 전달한다 — merge 훅 경로가 명령의
    `--repo`를 뽑아 조회에 넘기는 것과 같은 조회 함수를 공유하므로, CLI로 직접
    호출하는 이 경로도 저장소를 지정할 수 있어야 한 쪽만 고쳐지는 어긋남이
    없다(main()의 `--repo`/`-R` 옵션이 이 값을 채운다).
    """
    data, reason = _fetch_pr_body(identifier, repo)
    if data is None:
        return [reason or "PR 조회 실패(gh pr view)"]
    violations = check_pr_body(data["body"], require_checklist_complete=True)
    violations.extend(
        check_review_evidence(data.get("comments") or [], data.get("headRefOid") or "")
    )
    return violations


class HookSubcommand(enum.Enum):
    """훅이 받은 명령이 `gh pr` 어느 서브커맨드인지 — 값으로 승격한 것.

    이전엔 이 구분이 `(body, reason)` 튜플의 `None` 여부 조합과 `is_merge`
    참거짓 플래그(한 번 참으로 놓았다가 다음 블록에서 거짓으로 되돌리는 식)에
    흩어져 있었다. 되돌리기 자체는 결함이 아니었지만(다섯 경로 모두 낙관적으로
    참을 놓고 아니면 되돌리는 논리로 맞았다), "어느 서브커맨드인가"가 값이
    아니라 판별 순서에 의존해 흩어져 있었다 — 이 enum이 그 값을 한 곳에
    묶는다."""

    CREATE = "create"
    MERGE = "merge"
    COMMENT = "comment"
    NONE = "none"  # gh pr create·merge·comment 어느 것도 아님 — 검사 대상 아님


@dataclass
class HookResolution:
    """`run_hook`이 명령을 판별한 결과 — 서브커맨드 종류와 그에 딸린 본문·리젝
    사유·머지 스냅샷을 한 값으로 묶는다(판별 순서에 의존하던 상태를 값으로 승격).

    `body`가 None이고 `reason`도 None이면 검사 대상이 아니다(통과). `body`가
    None이고 `reason`이 있으면 본문을 못 들여다봐 리젝한다(fail-closed). 그
    밖엔 `body`로 검사를 진행한다 — 이 세 조합은 여전히 유효하다(계약을 바꾸지
    않았다), 이 값은 그 조합에 "어느 서브커맨드가 이 조합을 냈는가"만 얹는다.
    """

    kind: HookSubcommand
    body: str | None = None
    reason: str | None = None
    merge_view: dict | None = None


def _resolve_hook_command(command: str) -> HookResolution:
    """`command`가 `gh pr create`·`merge`·`comment` 중 무엇인지, 검사할 본문이
    무엇인지 판별한다 — create부터 순서대로 시도하고, 앞 서브커맨드가 자기
    소관이 아니라고 답하면(`(None, None)`) 다음으로 넘어간다."""
    body, reason = extract_body_from_command(command)
    if body is not None or reason is not None:
        return HookResolution(HookSubcommand.CREATE, body=body, reason=reason)

    # gh pr create가 아님 — gh pr merge인지 본다.
    merge_view, reason = extract_pr_view_from_merge_command(command)
    if merge_view is not None or reason is not None:
        body = merge_view["body"] if merge_view is not None else None
        return HookResolution(
            HookSubcommand.MERGE, body=body, reason=reason, merge_view=merge_view
        )

    # gh pr merge도 아님 — gh pr comment인지 본다(셋 다 아니면 NONE).
    body, reason = extract_body_from_comment_command(command)
    if body is not None or reason is not None:
        return HookResolution(HookSubcommand.COMMENT, body=body, reason=reason)

    return HookResolution(HookSubcommand.NONE)


def _review_repeat_violations(command: str, body: str) -> list[str]:
    """`check_review_repeat`에 필요한 조회를 훅에서 붙인다.

    조회는 **리뷰 종합일 때만** 한다 — 일반 코멘트가 네트워크 왕복을 무는 것을
    막는다. 조회 실패는 fail-open이다. merge 경로의 fail-closed와 갈리는 근거는
    이 검사가 최종 방어선이 아니라서다 — 놓쳐도 `check_review_evidence`가 머지
    시점에 SHA 신선도로 다시 잡는다. 반대로 fail-closed로 하면 gh가 안 닿는
    자리에서 코멘트 작성 자체가 막힌다(검사 하나를 위해 작업을 세우는 셈).
    """
    prefix = load_review_header_prefix()
    if prefix is None:
        return []
    pattern = _review_header_pattern(prefix)
    if not any(pattern.match(line.strip()) for line in body.splitlines()):
        return []  # 리뷰 종합 아님 — 조회하지 않는다
    is_comment, identifier, repo, _reason = resolve_comment_call(command)
    if not is_comment:
        return []
    data, _unreadable = _fetch_pr_body(identifier, repo)
    if data is None:
        return []  # fail-open — 위 docstring
    return check_review_repeat(body, data.get("comments") or [])


def run_hook() -> int:
    """Claude Code PreToolUse 훅. stdin=훅 JSON. exit 2 = 툴 호출 리젝."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"[check_pr_body] 훅 payload 파싱 실패: {e}", file=sys.stderr)
        return 1  # 논블로킹 — 훅 자체 고장으로 작업을 막지는 않는다

    command = (payload.get("tool_input") or {}).get("command", "")
    # create = 리뷰 요청 시점이라 체크리스트 완료를 요구하지 않는다(형식만).
    # merge = 리뷰 끝난 뒤라 체크리스트 전량 + 리뷰 종합 코멘트 존재·신선도까지
    # 요구한다(백스톱, check_review_evidence).
    # comment = PR 본문이 아니라 근거 기록 — 섹션·체크리스트 없이 분량·문장·
    # 용어 풀이만 강제한다(check_comment).
    resolved = _resolve_hook_command(command)

    if resolved.body is None:
        if resolved.kind is HookSubcommand.NONE:
            return 0  # gh pr create·merge·comment 어느 것도 아님 — 검사 대상 아님
        print(f"[check_pr_body] PR 본문 리젝 — {resolved.reason}", file=sys.stderr)
        return 2

    if resolved.kind is HookSubcommand.COMMENT:
        violations = check_comment(resolved.body) + _review_repeat_violations(
            command, resolved.body
        )
        if violations:
            _report_comment(violations, resolved.body)
            return 2
        return 0

    if resolved.kind is HookSubcommand.CREATE:
        # create만 — 제목 conventional-commit 게이트(S5). merge는 이미 만들어진
        # PR을 가리킬 뿐 제목을 새로 짓지 않으므로 검사 대상이 아니다.
        title, _ = extract_title_from_command(command)
        if title is not None:
            title_violations = check_pr_title(title)
            if title_violations:
                _report_title(title_violations, title)
                return 2

    is_merge = resolved.kind is HookSubcommand.MERGE
    violations = check_pr_body(resolved.body, require_checklist_complete=is_merge)
    if is_merge and resolved.merge_view is not None:
        # 백스톱: 체크리스트가 전량 체크돼도 리뷰 종합 코멘트가 없거나 낡았으면
        # 여전히 리젝한다(check_review_evidence를 훅이 처음 강제).
        violations = violations + check_review_evidence(
            resolved.merge_view.get("comments") or [],
            resolved.merge_view.get("headRefOid") or "",
        )
    if violations:
        _report(violations, resolved.body)
        return 2
    return 0


def run_merge_check(identifier: str, repo: str | None = None) -> int:
    """`--merge-check` dry-run 진입점 — **`gh pr merge`를 부르지 않는다.**
    `check_merge_readiness`의 판정을 사람이 읽을 출력으로 옮길 뿐이다."""
    violations = check_merge_readiness(identifier, repo)
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


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog=prog, description="PR 본문 구조·분량 게이트")
    ap.add_argument("--body-file", type=Path, help="검사할 PR 본문 파일")
    ap.add_argument("--hook", action="store_true",
                    help="Claude Code PreToolUse 훅 모드(stdin=훅 JSON)")
    ap.add_argument("--merge-check", metavar="PR",
                    help="머지 준비 dry-run 검사(실제 머지 안 함) — 대상 PR 번호·브랜치·URL")
    ap.add_argument("--repo", "-R", metavar="OWNER/REPO", default=None,
                    help="--merge-check 대상 저장소(gh pr view --repo와 동일) — "
                         "생략하면 현재 디렉터리의 remote로 추론된다")
    args = ap.parse_args(argv)

    if args.hook:
        return run_hook()
    if args.merge_check is not None:
        return run_merge_check(args.merge_check, args.repo)
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
