#!/usr/bin/env python3
# BLUF: PR 본문이 필수 섹션을 갖췄고 각 섹션이 글자 예산 안인지 판정하는 룰 게이트(stdlib only, LLM 0) — Claude Code PreToolUse 훅으로 `gh pr create`·`gh pr merge`를 리젝한다.
"""PR 본문 구조·분량 게이트.

`gh pr create`로 올라가는 본문이 `.github/PULL_REQUEST_TEMPLATE.md`의 섹션을
갖췄는지, 각 섹션이 예산 안인지 검사한다. 언어 지시("짧게 써라")가 안 지켜지므로
구조로 강제한다(원칙 1). `gh pr merge`도 같은 검사기로 리젝한다 — 대상 PR의
현재 본문을 `gh pr view --json body`로 조회해 같은 판정을 재사용한다("머지는
사장 몫" 규약을 처음 기계로 강제, docs/handoff/2-now-state.md).

**예산을 섹션별로 쪼갠 이유**: 총량만 걸면 저자가 어느 섹션을 죽일지 스스로
고른다 — 서사가 붙기 쉬운 요약이 부풀고, 리뷰어에게 정작 필요한 검증·범위밖이
0자가 된다. 섹션별 상한은 그 선택권을 뺏는다.

**모드**:
  python scripts/check_pr_body.py --body-file BODY.md   # CLI 검사(exit 1 = 위반)
  python scripts/check_pr_body.py --hook                 # Claude Code PreToolUse
                                                         # (stdin=훅 JSON, exit 2 = 리젝)

훅 모드는 본문을 못 들여다보는 호출(`--fill`, 에디터 대화형, `gh pr merge`의
`gh pr view` 조회 실패 등)도 리젝한다(fail-closed) — 검사를 우회할 수 있으면
게이트가 아니다(자기보고 불신, 원칙 2).
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

# 이 dict가 PR 본문 예산의 정본이다 — 규칙 09·템플릿·문서는 이 값을 재서술하지
# 말고 이 파일을 가리킬 것(규칙 08 제3조). 위반 메시지가 실측값과 함께
# 예산을 알려주므로 저자는 여기를 안 읽어도 된다.
SECTION_BUDGETS: dict[str, int] = {
    "요약": 150,
    "변경": 300,
    "범위 밖": 100,
    "검증": 150,
}

# 기계가 판정 못 하는 항목의 자기신고 섹션. 예산 대상이 아니다(문구가 고정이라
# 저자가 줄일 수 없다). **이 섹션은 강제가 아니라 자기보고다** — 원칙 2가 믿지
# 말라고 한 바로 그 형태이므로, 여기 체크가 곧 사실이라고 읽어서는 안 된다.
CHECKLIST_SECTION = "확인"

# 문장 종결 마침표 — check_doc_form과 동일 규칙("한 줄 한 문장")이다. 두
# 스크립트는 stdlib only(훅에서 vgo 설치 없이 돈다)라 import로 합칠 수 없어
# 정규식을 복제한다. 앞이 숫자·마침표면 배제(소수·번호·말줄임), 뒤가 공백
# 아니면 배제(코드·경로), 뒤에 다음 문장(비공백)이 이어질 때만 걸린다.
_SENTENCE_END = re.compile(r"(?<![0-9.])\. (?=\S)")
REQUIRED_CHECKS: tuple[str, ...] = (
    "가독성을 높이는 검수를 진행했다",
    "과한 내부 은어 사용 검수했다",
    "비전문가, 제3자도 쉽게 이해할 수 있도록 작성되었는지 검토했다",
    "이 변경이 다른 문서를 낡게 하지 않았는지 검토했다",
    "바꾼 값·사실을 옮겨 적은 다른 문서도 같이 고쳤는지 확인했다",
    "이 문서를 가리키던 링크·참조가 끊기지 않았는지 확인했다",
    "영향받는 문서의 요약(맨 위 한 줄)이 여전히 맞는지 확인했다",
)

# 제3자가 한 번에 못 읽는 이 저장소의 내부 용어 — 첫 등장에 괄호 풀이를 요구한다
# (금지가 아니다. 그 용어가 주제인 PR을 못 쓰게 되면 게이트가 꺼진다).
# **완결 목록이 아니라 상습범 목록이다** — 여기 없는 은어가 통과하는 게 정상이고,
# 일반적 가독성은 리뷰어 판정에 남는다(규칙 09 "강제 수단"). 새 상습범은 여기 추가.
JARGON_TERMS: tuple[str, ...] = (
    "L2", "seam", "BLUF", "altitude", "provenance", "ship-ok",
    "도그푸딩", "워터마크", "서브레포", "폴백", "밴드에이드", "원장",
    "청킹", "인제스트", "델타갱신", "스튜어드",
    # 상습범은 관측되는 대로 늘린다(규칙 09 — 목록은 바닥이지 증명이 아니다).
    # 아래는 게이트 작업 세션 PR 본문들에서 풀이 없이 반복 샌 것들.
    "fail-open", "fail-closed", "캐스케이드",
)

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_GLOSS_AFTER = re.compile(r"^\s*[(（]")
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
                f"'{term}(쉬운 말 설명)' 형태로 풀어라. 이 저장소를 모르는 "
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
    항목이 참이라는 증거가 아니다 — 판정은 여전히 리뷰어 몫이다(원칙 2).
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


def check_pr_body(body: str) -> list[str]:
    """위반 목록을 반환한다(빈 리스트 = 통과)."""
    sections = parse_sections(body)
    violations: list[str] = []

    for name, budget in SECTION_BUDGETS.items():
        if name not in sections:
            violations.append(f"섹션 '## {name}' 없음 — 템플릿 4개 섹션은 필수다.")
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
    violations.extend(check_checklist(sections))

    allowed = set(SECTION_BUDGETS) | {CHECKLIST_SECTION}
    unknown = [s for s in sections if s not in allowed]
    if unknown:
        violations.append(
            f"템플릿에 없는 섹션: {', '.join(unknown)} — "
            f"허용 섹션은 {', '.join(allowed)} 뿐이다."
        )
    violations.extend(check_jargon(body))
    return violations


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
        "\n형식: .github/PULL_REQUEST_TEMPLATE.md · 근거: docs/rules/09-pr-body-structure.md",
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


def _is_gh_pr_create(argv: list[str]) -> bool:
    """`gh pr create`가 복합 명령(`cd x && gh pr create ...`) 안에 있어도 잡는다.
    인접 3토큰을 요구해 `gh issue create`·`gh pr view` 오탐을 배제한다."""
    return any(
        Path(argv[i]).name == "gh" and argv[i + 1] == "pr" and argv[i + 2] == "create"
        for i in range(len(argv) - 2)
    )


def extract_body_from_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr create ...`에서 본문을 뽑는다.

    반환: (body, reason_if_uninspectable). gh 호출이 아니면 (None, None) —
    호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:  # 따옴표 안 닫힘 등 — 셸이 알아서 죽는다
        return None, f"명령 파싱 실패({e})"

    if not _is_gh_pr_create(argv):
        return None, None

    for i in range(len(argv)):
        tok = argv[i]
        if tok in _BODY_FLAGS and i + 1 < len(argv):
            return argv[i + 1], None
        if tok.startswith("--body="):
            return tok.split("=", 1)[1], None
        if tok in _BODY_FILE_FLAGS and i + 1 < len(argv):
            return _resolve_body_file(argv[i + 1])
        if tok.startswith("--body-file="):
            return _resolve_body_file(tok.split("=", 1)[1])

    return None, "본문이 명령에 없음(--fill·에디터 대화형 등) — --body-file로 넘겨라"


# --- gh pr merge 게이트 ------------------------------------------------------
#
# "머지는 사장 몫 — 감독·구현자는 머지하지 않는다"가 이미 규약이었으나
# (docs/handoff/2-now-state.md) 게이트가 0이었다 — 이 절이 그걸 처음
# 기계로 강제한다. `gh pr create`와 달리 본문이 명령 인자에 없다(머지 시점엔
# 이미 작성된 PR을 가리킬 뿐이므로) — `gh pr view --json body`로 능동 조회한다.

def _is_gh_pr_merge(argv: list[str]) -> bool:
    """`gh pr merge`가 복합 명령(`cd x && gh pr merge ...`) 안에 있어도 잡는다.
    인접 3토큰을 요구해 `gh pr view`·`gh issue merge` 등 오탐을 배제한다."""
    return any(
        Path(argv[i]).name == "gh" and argv[i + 1] == "pr" and argv[i + 2] == "merge"
        for i in range(len(argv) - 2)
    )


# gh pr merge의 값-소비 플래그 — 이 값 토큰을 PR 식별자로 오인하면 안 된다
# (예: `gh pr merge --subject "메시지"`에서 "메시지"는 식별자가 아니다).
_MERGE_VALUE_FLAGS = {"--subject", "-t", "--body", "-b", "--body-file",
                       "-F", "--match-head-commit"}


def _merge_target(argv: list[str]) -> str | None:
    """`gh pr merge [<번호|브랜치|URL>] [옵션...]`에서 대상 식별자를 뽑는다.
    옵션이 아닌 첫 토큰이 식별자다 — 단, `--subject`/`--body` 같은 값-소비
    플래그의 값 토큰은 건너뛴다(안 그러면 그 값을 식별자로 오인해 정상 머지를
    오탐 리젝한다). 식별자가 생략되면(gh가 현재 브랜치를 추론) None."""
    for i in range(len(argv) - 2):
        if Path(argv[i]).name == "gh" and argv[i + 1] == "pr" and argv[i + 2] == "merge":
            skip_next = False
            for tok in argv[i + 3:]:
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


def _fetch_pr_body(identifier: str | None) -> tuple[str | None, str | None]:
    """`gh pr view [<식별자>] --json body`로 대상 PR의 현재 본문을 조회한다.

    반환: (body, reason_if_unreadable). 조회 자체가 실패하면(gh 미설치·인증 안
    됨·PR 번호 틀림 등) 본문을 못 들여다본 것과 같으므로 fail-closed로 취급한다
    (제3조 "검사 우회 금지"와 같은 원칙 — 못 보면 통과가 아니라 리젝).
    """
    cmd = ["gh", "pr", "view"]
    if identifier is not None:
        cmd.append(identifier)
    cmd += ["--json", "body"]
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
    body = data.get("body")
    if not body:
        return None, "gh pr view 응답에 본문이 없거나 비어 있음"
    return body, None


def extract_body_from_merge_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr merge ...`가 리젝 대상인 PR의 본문을 `gh pr view`로 조회해 뽑는다.

    반환: (body, reason_if_uninspectable). gh pr merge 호출이 아니면 (None, None)
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


def run_hook() -> int:
    """Claude Code PreToolUse 훅. stdin=훅 JSON. exit 2 = 툴 호출 리젝."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"[check_pr_body] 훅 payload 파싱 실패: {e}", file=sys.stderr)
        return 1  # 논블로킹 — 훅 자체 고장으로 작업을 막지는 않는다

    command = (payload.get("tool_input") or {}).get("command", "")
    body, reason = extract_body_from_command(command)
    if body is None and reason is None:
        # gh pr create가 아님 — gh pr merge인지 본다(둘 다 아니면 통과).
        body, reason = extract_body_from_merge_command(command)

    if body is None:
        if reason is None:
            return 0  # gh pr create도 gh pr merge도 아님 — 검사 대상 아님
        print(f"[check_pr_body] PR 본문 리젝 — {reason}", file=sys.stderr)
        return 2

    violations = check_pr_body(body)
    if violations:
        _report(violations, body)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="PR 본문 구조·분량 게이트")
    ap.add_argument("--body-file", type=Path, help="검사할 PR 본문 파일")
    ap.add_argument("--hook", action="store_true",
                    help="Claude Code PreToolUse 훅 모드(stdin=훅 JSON)")
    args = ap.parse_args(argv)

    if args.hook:
        return run_hook()
    if not args.body_file:
        ap.error("--body-file 또는 --hook 중 하나가 필요하다")

    body = args.body_file.read_text(encoding="utf-8")
    violations = check_pr_body(body)
    if violations:
        _report(violations, body)
        return 1
    print(f"[check_pr_body] 통과 — {args.body_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
