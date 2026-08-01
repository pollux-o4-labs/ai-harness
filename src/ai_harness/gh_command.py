#!/usr/bin/env python3
# BLUF: `gh pr create`·`comment`·`merge` 명령 문자열에서 본문·제목·머지 대상·저장소 값을 뽑는다(stdlib only, gh 문법 전용) — PR 품질 판정(check_pr_body.py)과 무관한 순수 파싱 계층.
"""gh 명령줄 값 추출 — 셸 문법이 아니라 gh 문법을 안다.

`shell_scan.py`가 문자열을 토큰·세그먼트로 가른다(셸 문법만 안다). 이 모듈은
그 다음 층이다 — 세그먼트에서 `gh pr <subcommand>`의 플래그값(본문·제목·머지
대상·저장소)을 뽑는다(gh 문법만 안다). 의존은 `shell_scan` 하나뿐이고, PR
품질 판정 모듈(`check_pr_body.py`)을 부르지 않는다 — 순환이 없다(그쪽이 이
모듈을 부르는 한 방향).

**파싱은 실패하면 예외이거나 값 없음이다** — `check_pr_body.py`의 조회
함수(`gh pr view` 실행)와 실패 정책이 다르다. 조회는 실패하면 리젝이지만,
이 모듈의 함수는 "그 서브커맨드가 아니다"·"플래그가 없다"를 그대로
`(None, None)` 등으로 반환한다 — 호출자가 자기 정책(리젝할지 통과시킬지)을
정한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from ai_harness.shell_scan import SHELL_OPERATORS, tokenize

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
# CRITICAL(실사고): 주석 한 줄("# gh pr comment preceded by env assignment")이
# 토큰화 결과에서 "gh","pr","comment"로 인접해 gh 호출로 오인됐다 — gh를
# 부르지도 않은 명령이 리젝됐다. 공용 `tokenize`가 주석을 인식하므로 그 사례는
# 재발하지 않는다. 다만 **완전한 해결은 아니다** — heredoc과 문자열 안 평문은
# 이 토큰화로도 구별하지 못한다. 그래서 두 방어를 유지한다 —
# (1) --body/--body-file 탐색을 매칭된 gh 호출과 같은 셸 세그먼트로 좁혀 무관한
# 다른 명령의 플래그를 오인해 붙잡지 않게 하고(국소성), (2) 그래도 리젝될 땐
# 어떤 토큰을 gh 호출로 인식했는지 사유에 노출해 오탐 자기진단 비용을 줄인다.
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


def _gh_repo_value(argv: list[str], span: tuple[int, int]) -> str | None:
    """gh 호출이 속한 셸 세그먼트 전체에서 `--repo`/`-R` 값을 뽑는다.

    gh는 cobra 기반이라 이 플래그가 subcommand **앞**(`gh --repo o/r pr
    merge`)이든 **뒤**(`gh pr merge 44 --repo o/r`)든 다 받는다 — 실사고
    재현 명령이 후자였다(`gh pr merge 44 --repo pollux-o4-labs/ai-harness`).
    그래서 `pr` 토큰 앞까지가 아니라 `_segment_end`로 다음 셸 연산자
    (&&·||·;·|) 앞까지 전체를 본다 — `--body` 탐색의 국소성 원칙과 같다
    (`&&`로 이어진 다음 명령의 `--repo`를 이 호출 소속으로 오인하지 않는다).
    없으면 None(gh가 현재 디렉터리 remote로 판단하게 둔다 — 단일 저장소
    세션의 종전 동작을 그대로 보존한다).

    HIGH(선재 결함): `_GH_GLOBAL_VALUE_FLAGS`가 이미 이 플래그를 값-소비로
    인식해 subcommand 탐색에서 건너뛰지만, 그 값을 버리고 있었다 — 훅이
    호출자의 작업 디렉터리가 아니라 세션 기준 디렉터리에서 돌아 여러 저장소를
    오가면 `gh pr view`가 엉뚱한 저장소의 같은 번호 PR을 조회해 오판했다
    (실사고: 형제 저장소의 이미 머지된 PR을 검사·리젝). 이 값을 뽑아
    `_fetch_pr_body`에 그대로 넘기면 그 저장소로 조회를 고정한다.
    """
    gh_i, _subcmd_i = span
    end = _segment_end(argv, gh_i + 1)
    j = gh_i + 1
    while j < end:
        tok = argv[j]
        if tok in ("--repo", "-R") and j + 1 < end:
            return argv[j + 1]
        if tok.startswith("--repo="):
            return tok.split("=", 1)[1]
        j += 1
    return None


def _segment_end(argv: list[str], start: int) -> int:
    """`start`부터 다음 셸 연산자 토큰(&&·||·;·|) 직전까지의 인덱스(exclusive).
    없으면 len(argv). --body/--body-file 탐색을 매칭된 gh 호출과 같은 셸
    문장 안으로만 좁힌다(국소성) — `&&`로 이어진 다음 명령의 플래그를 이
    호출 소속으로 오인하지 않는다."""
    for j in range(start, len(argv)):
        if argv[j] in SHELL_OPERATORS:
            return j
    return len(argv)


def _segment_bounds(argv: list[str], span: tuple[int, int]) -> tuple[int, int]:
    """매칭된 gh 호출(span) 뒤부터 같은 셸 세그먼트 끝까지의 `[start, end)`
    범위 — `subcmd_i + 1`과 `_segment_end` 조합을 한 곳에 모은다.
    `_body_from_match`·`extract_title_from_command`가 공유한다(리뷰
    SHOULD-FIX#2, 3줄 복붙 제거)."""
    _, subcmd_i = span
    start = subcmd_i + 1
    return start, _segment_end(argv, start)


def _match_diagnostic(argv: list[str], span: tuple[int, int], subcommand: str) -> str:
    """리젝 사유에 붙일 자기진단 힌트 — 어떤 토큰을 `gh pr <subcommand>`로
    인식했는지 위치·내용을 노출한다. 오탐(주석·heredoc 안 평문 등)이어도
    근본 해결이 불가능하니, 사람이 그 위치를 보고 즉시 오탐임을 판별하게
    하는 것으로 대신한다."""
    gh_i, subcmd_i = span
    return (
        f" [진단: 'gh ... pr {subcommand}'로 인식한 토큰 {gh_i}..{subcmd_i}="
        f"{argv[gh_i:subcmd_i + 1]!r} — 토큰화는 셸 구조를 완전히 알지 못한다"
        f"(heredoc·문자열 안 평문도 매칭될 수 있음). 오탐이면 그 주변 원문을 "
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
    start, end = _segment_bounds(argv, span)
    body, reason = _body_from_argv(argv, start=start, end=end)
    if body is None and reason is not None:
        reason = reason + _match_diagnostic(argv, span, subcommand)
    return body, reason


def _extract_body_for_subcommand(command: str, subcommand: str) -> tuple[str | None, str | None]:
    """`gh pr <subcommand> ...`에서 본문을 뽑는다 — create·comment가 공유하는
    본체(대상 서브커맨드 문자열만 다르다). 공개 함수 이름·시그니처는 각자
    그대로 두고(테스트가 이름을 직접 부른다) 이 헬퍼를 얇게 감싼다.

    반환: (body, reason_if_uninspectable). gh 호출이 아니면 (None, None) —
    호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    try:
        argv = tokenize(command)
    except ValueError as e:  # 따옴표 안 닫힘 등 — 셸이 알아서 죽는다
        return None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, subcommand)
    if span is None:
        return None, None

    return _body_from_match(argv, span, subcommand)


def extract_body_from_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr create ...`에서 본문을 뽑는다.

    반환: (body, reason_if_uninspectable). gh 호출이 아니면 (None, None) —
    호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    return _extract_body_for_subcommand(command, "create")


def extract_body_from_comment_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr comment ...`에서 코멘트 본문을 뽑는다. `gh pr create`와 같은
    `--body`/`--body-file` 파싱을 재사용한다(둘 다 같은 플래그 계약).

    반환: (body, reason_if_uninspectable). gh pr comment 호출이 아니면
    (None, None) — 호출자가 '검사 대상 아님'으로 통과시킨다.
    """
    return _extract_body_for_subcommand(command, "comment")


# --- gh pr create 제목(S5): conventional-commit 형식 검사는 다른 축이다 ------
#
# 제목 형식(conventional-commit) 판정은 PR 품질 판정 축이라 여기 없다
# (`check_pr_body.check_pr_title`) — 이 모듈은 명령에서 제목 값을 뽑는
# 파싱까지만 한다.

_TITLE_FLAGS = {"--title", "-t"}


def extract_title_from_command(command: str) -> tuple[str | None, str | None]:
    """`gh pr create ...`에서 제목을 뽑는다 — `extract_body_from_command`의
    거울상(같은 `_find_gh_pr_span`·`_segment_bounds` 국소성 규약을 공유한다).
    `gh pr create`가 아니면 (None, None) — 호출자가 '검사 대상 아님'으로
    통과시킨다.

    **제목 플래그가 없어도 (None, None)이다(fail-open)** — body와 다른
    선택이다. body는 플래그가 없으면 리젝 사유를 낸다(우회 차단, 모듈
    docstring 참조). **이 게이트는 명령에 명시된 제목(`--title`/`-t`류
    형태)만 검증한다** — `--fill` 등 gh가 커밋에서 파생하는 제목은 argv에
    아예 없어 이 게이트 사정권 밖이다(커밋 메시지 관심사이지 PR 제목 형식
    관심사가 아니다, 별도 축). 그래서 제목 플래그가 없으면 통과시킨다 —
    "제목이 있으면 형식을 강제하고, 없으면 검사하지 않는다"가 의도된
    스코프다(body처럼 부재 자체를 우회로 보지 않는다). 주의: "제목 부재는
    body 부재로 이미 막힌다"고 보면 안 된다 — `--fill --body-file <정상
    본문>`처럼 body는 있고 제목만 없는 호출이 성립하므로, 제목 검사는
    명시된 제목에만 걸린다.

    붙임 단축형(`-tVALUE`·`-t=VALUE`)도 잡는다(리뷰 SHOULD-FIX#1) — 못 잡으면
    제목이 실재하는데도 이 게이트가 못 읽어 fail-open으로 새는 우회구가 된다.
    `-t`는 gh pr create에서 title 전용 단축 플래그라 다른 뜻과 안 겹친다.

    반환: (title, reason_if_uninspectable).
    """
    try:
        argv = tokenize(command)
    except ValueError as e:
        return None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, "create")
    if span is None:
        return None, None

    start, end = _segment_bounds(argv, span)
    for i in range(start, end):
        tok = argv[i]
        if tok in _TITLE_FLAGS and i + 1 < end:
            return argv[i + 1], None
        if tok.startswith("--title="):
            return tok.split("=", 1)[1], None
        if tok.startswith("-t="):
            return tok[3:], None
        if tok.startswith("-t") and not tok.startswith("--") and len(tok) > 2:
            return tok[2:], None
    return None, None


# --- gh pr merge 대상·저장소 --------------------------------------------------

def _is_gh_pr_merge(argv: list[str]) -> bool:
    """`gh pr merge`가 복합 명령(`cd x && gh pr merge ...`) 안에 있어도 잡는다.
    `_find_gh_pr_span`을 재사용 — create·comment와 같은 전역 플래그 완화를
    받는다(HIGH-2, 선재 결함: `gh --repo o/r pr merge`도 이제 잡힌다)."""
    return _find_gh_pr_span(argv, "merge") is not None


# gh pr merge의 값-소비 플래그 — 이 값 토큰을 PR 식별자로 오인하면 안 된다
# (예: `gh pr merge --subject "메시지"`에서 "메시지"는 식별자가 아니다).
_MERGE_VALUE_FLAGS = {"--subject", "-t", "--body", "-b", "--body-file",
                       "-F", "--match-head-commit"}


def _merge_target(argv: list[str], subcommand: str = "merge") -> str | None:
    """`gh pr <subcommand> [<번호|브랜치|URL>] [옵션...]`에서 대상 식별자를 뽑는다.
    옵션이 아닌 첫 토큰이 식별자다 — 단, `--subject`/`--body` 같은 값-소비
    플래그의 값 토큰은 건너뛴다(안 그러면 그 값을 식별자로 오인해 정상 머지를
    오탐 리젝한다). 식별자가 생략되면(gh가 현재 브랜치를 추론) None.

    이름은 merge를 가리키지만 `comment`도 같은 위치인자 계약을 써서 공유한다
    (`resolve_comment_call`). 값-소비 플래그 집합도 comment의 것(`--body`·`-b`·
    `--body-file`·`-F`)을 이미 품고 있어 그대로 맞는다 — comment에 없는
    `--subject` 따위가 집합에 남아도 그 토큰이 안 나타나므로 무해하다.
    개명하지 않는 것은 이 이름을 직접 부르는 검사가 이미 있어서다."""
    span = _find_gh_pr_span(argv, subcommand)
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


def resolve_merge_call(command: str) -> tuple[bool, str | None, str | None, str | None]:
    """`gh pr merge ...` 호출인지 판별해 대상 식별자·저장소·판별 불가 사유를
    한 자리에서 낸다 — `_is_gh_pr_merge`·`_merge_target`·`_find_gh_pr_span`·
    `_gh_repo_value` 넷을 이 함수 하나가 조립한다.

    호출자가 예전엔 이 넷을 직접 불렀다. 그러면 게이트 파일이 이 모듈의
    비공개 이름 둘을 밖에서 가져다 써야 해 속이 새어 나온다. 이 함수를
    두어 호출자가 이것 하나와 `gh pr view` 조회 함수만 부르게 한다.

    **`_find_gh_pr_span`은 여전히 세 번 돈다**(판별·식별자·저장소).
    이 함수가 그 중복을 없애지는 않는다 — 계산 자리가 이 모듈 안으로
    들어왔을 뿐이다. 없애려면 위치를 미리 구해 넷에 넘겨야 하는데,
    그러면 `_merge_target`의 계약이 바뀌어 그것을 직접 부르는 검사가 깨진다.
    스캔이 작아 실해가 없으므로 그대로 둔다.

    반환: (is_merge, identifier, repo, reason).
      - 명령 파싱 자체가 실패하면(따옴표 안 닫힘 등) `(False, None, None,
        사유)` — `is_merge`가 아니라 `reason`으로 "판별 자체가 안 됐다"를
        알린다.
      - `gh pr merge` 호출이 아니면 `(False, None, None, None)` — 호출자가
        '검사 대상 아님'으로 통과시킨다. 식별자·저장소가 둘 다 생략된 정상
        merge 호출과 같은 모양(전부 None)이 되므로, 그 둘을 가르는 신호는
        `is_merge`뿐이다(식별자·저장소의 None 여부로는 못 가른다 — 식별자는
        생략 가능한 값이다).
      - `gh pr merge` 호출이면 `(True, identifier, repo, None)` — identifier는
        생략됐으면 None(gh가 현재 브랜치를 추론), repo는 `--repo`/`-R`이
        없으면 None(gh가 현재 디렉터리 remote로 추론).
    """
    try:
        argv = tokenize(command)
    except ValueError as e:
        return False, None, None, f"명령 파싱 실패({e})"

    if not _is_gh_pr_merge(argv):
        return False, None, None, None

    identifier = _merge_target(argv)
    span = _find_gh_pr_span(argv, "merge")
    repo = _gh_repo_value(argv, span) if span is not None else None
    return True, identifier, repo, None


def resolve_comment_call(command: str) -> tuple[bool, str | None, str | None, str | None]:
    """`gh pr comment ...`의 대상 식별자·저장소를 낸다 — `resolve_merge_call`과
    같은 계약이며 서브커맨드만 다르다.

    코멘트 본문 자체는 명령 인자에 있어 `extract_body_from_comment_command`가
    이미 뽑는다. 이 함수가 필요한 곳은 **그 PR에 이미 달린 코멘트를 조회해야
    하는 검사**뿐이다(직전 리뷰 종합과의 대조). 저장소를 같이 내는 이유는
    merge와 같다 — 훅은 세션 기준 디렉터리에서 돌아 gh의 remote 추론이 형제
    저장소를 가리킬 수 있다.

    반환: (is_comment, identifier, repo, reason) — 의미는 `resolve_merge_call`과
    같다.
    """
    try:
        argv = tokenize(command)
    except ValueError as e:
        return False, None, None, f"명령 파싱 실패({e})"

    span = _find_gh_pr_span(argv, "comment")
    if span is None:
        return False, None, None, None

    identifier = _merge_target(argv, "comment")
    repo = _gh_repo_value(argv, span)
    return True, identifier, repo, None
