# BLUF: gh_command(gh 명령줄 값 추출)의 순수 단위테스트 — 본문·제목·머지 대상·저장소 파싱만 검사. 훅 통합·`gh pr view` 조회를 대역으로 세우는 검사는 test_check_pr_body.py에 남는다.
"""tests/test_gh_command.py — gh 명령줄 파싱 단위테스트.

DB도 LLM도 안 쓴다 — 순수 문자열 판정이라 어디서 돌려도 같은 결과다.

`check_pr_body.py`에서 갈라져 나온 시험이다(gh_command.py 분리,
refactor/gh-command 슬라이스). 명령 문자열만 다루는 검사만 여기로 왔다 — 훅
exit 코드·`gh pr view` 조회를 스텁하는 검사는 원 파일에 남는다(조회 정책은
이 모듈의 관심사가 아니다, gh_command.py 모듈 docstring 참고). 옮기면서
공개 계약(반환 규약·함수 이름)은 하나도 바꾸지 않았다.
"""
from __future__ import annotations

import pytest

import ai_harness.gh_command as ghc

# 파싱 대상 텍스트는 내용을 안 본다 — 어떤 문자열이든 그대로 왕복하면 된다
# (섹션·예산 판정은 check_pr_body.py의 관심사이지 이 모듈의 관심사가 아니다).
_SAMPLE_BODY = "PR 본문 예시 텍스트.\n"
_SAMPLE_COMMENT = "코멘트 예시 텍스트.\n"


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
    p.write_text(_SAMPLE_BODY, encoding="utf-8")
    body, reason = ghc.extract_body_from_command(cmd.format(p=p))
    assert reason is None
    assert body == _SAMPLE_BODY


def test_extract_body_inline():
    body, reason = ghc.extract_body_from_command('gh pr create --body "짧은 본문"')
    assert (body, reason) == ("짧은 본문", None)
    body, reason = ghc.extract_body_from_command('gh pr create --body=짧은본문')
    assert (body, reason) == ("짧은본문", None)


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh issue create --body x",   # pr create 아님
    "gh pr view 12",
    "echo 'gh pr create' > note.txt",  # 인접 3토큰이 아님
])
def test_non_target_commands_are_not_inspected(cmd):
    """검사 대상이 아니면 (None, None) — 훅이 통과시켜야 한다."""
    assert ghc.extract_body_from_command(cmd) == (None, None)


def test_uninspectable_call_is_fail_closed():
    """본문을 못 들여다보는 호출은 리젝 사유가 붙는다(우회 차단)."""
    body, reason = ghc.extract_body_from_command("gh pr create --fill")
    assert body is None and reason is not None


def test_missing_body_file_is_fail_closed(tmp_path):
    body, reason = ghc.extract_body_from_command(
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
    body, reason = ghc.extract_body_from_command(f"gh pr create --body-file {raw}")
    assert body is None
    assert "쉘 확장" in reason and "리터럴" in reason


# --- gh pr merge 대상 추출 ----------------------------------------------------

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
    assert ghc._merge_target(argv) == expected


# --- gh 명령에서 코멘트 본문 추출 ---------------------------------------------

@pytest.mark.parametrize("cmd", [
    'gh pr comment 42 --body-file {p}',
    'gh pr comment 42 --body-file={p}',
    'gh pr comment 42 -F {p}',
    'cd /repo && gh pr comment 42 --body-file {p}',
])
def test_extract_body_from_comment_command_file(tmp_path, cmd):
    p = tmp_path / "comment.md"
    p.write_text(_SAMPLE_COMMENT, encoding="utf-8")
    body, reason = ghc.extract_body_from_comment_command(cmd.format(p=p))
    assert reason is None
    assert body == _SAMPLE_COMMENT


def test_extract_body_from_comment_inline():
    body, reason = ghc.extract_body_from_comment_command(
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
    assert ghc.extract_body_from_comment_command(cmd) == (None, None)


def test_comment_uninspectable_call_is_fail_closed():
    """본문 플래그 없는 호출(에디터 대화형 등)은 리젝 사유가 붙는다."""
    body, reason = ghc.extract_body_from_comment_command("gh pr comment 42")
    assert body is None and reason is not None


# --- CRITICAL: 토큰화는 셸 구조를 완전히 알지 못한다 — 오탐 자기진단 ----------
#
# 실사고: 주석 한 줄("# gh pr comment preceded by env assignment")이 토큰화
# 결과에서 "gh","pr","comment"로 인접해 gh 호출로 오인됐고, 실제 --body가 없어
# exit 2로 리젝됐다(gh를 호출하지도 않은 명령이 막힘). 주석을 인식하는 토큰화로
# 바꾸어 그 사례는 재발하지 않는다. **완전한 해결은 아니다** — heredoc과 문자열
# 안 평문은 여전히 구별하지 못한다. 그래서 두 방어를 유지한다: (1) --body·
# --body-file 탐색을 매칭된 gh 호출과 같은 셸 세그먼트로 좁히고(국소성),
# (2) 리젝 사유에 어떤 토큰을 gh 호출로 인식했는지 노출해 자기진단 비용을 줄인다.

def test_comment_false_positive_in_prose_no_longer_triggers():
    """주석 속 평문은 더 이상 gh 호출로 오인되지 않는다.

    셸 연산자를 아는 토큰화로 바꾸면서 `#` 이후가 주석으로 인식되어 위
    실사고의 오탐 자체가 발생하지 않는다. 진단 노출은 여전히 필요하다 —
    heredoc·문자열 안 평문은 이 토큰화로도 구별하지 못한다."""
    command = "echo start\n# gh pr comment preceded by env assignment\necho end"
    body, reason = ghc.extract_body_from_comment_command(command)
    assert (body, reason) == (None, None)


def test_real_gh_call_after_comment_is_still_caught():
    """주석 인식이 우회로가 되어서는 아니 된다 — 실제 호출은 그대로 잡힌다."""
    body, reason = ghc.extract_body_from_command(
        '# 설명 한 줄\ngh pr create --title t --body "짧은 본문"'
    )
    assert (body, reason) == ("짧은 본문", None)


def test_comment_body_flag_before_match_is_not_used(tmp_path):
    """국소성: 매칭보다 앞선(무관한 다른 명령의) --body-file은 이 gh 호출
    소속으로 오인해선 안 된다 — 회귀: 예전엔 argv 전체를 인덱스 0부터 스캔해
    이런 파일 내용을 엉뚱하게 본문으로 썼다."""
    leftover = tmp_path / "leftover.md"
    leftover.write_text("- 무관한 내용입니다.\n", encoding="utf-8")
    command = f"cat --body-file {leftover} && gh pr comment 42"
    body, reason = ghc.extract_body_from_comment_command(command)
    assert body is None  # leftover.md 내용을 본문으로 쓰면 안 된다
    assert reason is not None  # 대신 '본문 없음'으로 fail-closed


def test_create_body_flag_after_next_segment_is_not_used(tmp_path):
    """국소성: 매칭된 gh 호출 뒤 `&&`로 이어진 무관한 다음 명령의 --body도
    이 호출 소속이 아니다."""
    command = 'gh pr create 2>/dev/null && echo unrelated --body "엉뚱한 본문"'
    body, reason = ghc.extract_body_from_command(command)
    assert body is None
    assert reason is not None


# --- HIGH-2: 전역 플래그(--repo/-R)가 gh 바로 뒤에 오면 놓친다 ----------------

def test_comment_recognizes_global_repo_flag():
    """`gh --repo o/r pr comment ...`처럼 전역 플래그가 subcommand 앞에 와도
    인식해야 한다 — 인접 3토큰 고정 매칭은 이걸 놓쳐 조용히 샌다(무검사 통과)."""
    body, reason = ghc.extract_body_from_comment_command(
        'gh --repo owner/repo pr comment 42 --body "짧은 코멘트"'
    )
    assert (body, reason) == ("짧은 코멘트", None)


def test_create_recognizes_global_repo_flag_short_form(tmp_path):
    """`-R` 단축형도 같은 함수라 create도 같이 고쳐진다(선재 결함)."""
    p = tmp_path / "body.md"
    p.write_text(_SAMPLE_BODY, encoding="utf-8")
    body, reason = ghc.extract_body_from_command(f"gh -R o/r pr create --body-file {p}")
    assert reason is None
    assert body == _SAMPLE_BODY


# --- gh pr create 제목 추출 ---------------------------------------------------
#
# 제목 형식(conventional-commit) 판정은 check_pr_body.check_pr_title이 한다
# (PR 품질 판정 축) — 여기는 명령에서 제목 값을 뽑는 파싱만 검사한다.

def test_extract_title_finds_long_flag():
    title, reason = ghc.extract_title_from_command(
        'gh pr create --title "feat: 새 기능" --body-file f'
    )
    assert (title, reason) == ("feat: 새 기능", None)


def test_extract_title_finds_short_flag():
    title, reason = ghc.extract_title_from_command(
        'gh pr create -t "fix: 버그" --body-file f'
    )
    assert (title, reason) == ("fix: 버그", None)


def test_extract_title_finds_equals_form():
    title, reason = ghc.extract_title_from_command(
        "gh pr create --title=fix:버그 --body-file f"
    )
    assert (title, reason) == ("fix:버그", None)


def test_extract_title_finds_short_flag_equals_form():
    """`-t=VALUE`도 파싱한다(회귀 — 리뷰 SHOULD-FIX#1) — 이전엔 못 읽어 제목이
    실재하는데도 fail-open으로 새는 우회구였다."""
    title, reason = ghc.extract_title_from_command(
        "gh pr create -t=fix:버그 --body-file f"
    )
    assert (title, reason) == ("fix:버그", None)


def test_extract_title_finds_short_flag_attached_form():
    """`-tVALUE`(공백 없는 붙임꼴)도 파싱한다(회귀 — 리뷰 SHOULD-FIX#1)."""
    title, reason = ghc.extract_title_from_command(
        'gh pr create -t"fix: 버그" --body-file f'
    )
    assert (title, reason) == ("fix: 버그", None)


def test_extract_title_absent_is_not_rejected():
    """제목 플래그가 없는 create 호출은 (None, None) — fail-open(설계 결정,
    gh_command.py 모듈 docstring 참조)."""
    assert ghc.extract_title_from_command("gh pr create --body-file f") == (None, None)


@pytest.mark.parametrize("cmd", [
    "git status",
    "gh pr merge 42 --subject t",
    "gh pr comment 42 --body x",
    "gh issue create --title t",
])
def test_extract_title_non_create_commands_not_inspected(cmd):
    """create가 아니면 (None, None) — 훅이 통과시켜야 한다(create 아닌 호출
    무영향)."""
    assert ghc.extract_title_from_command(cmd) == (None, None)


# --- 셸 연산자 경계 (회귀) ────────────────────────────────────────────────────
# `shlex.split`은 공백 분리 토크나이저라 셸 문법을 모른다 — 공백 없이 붙은
# 연산자를 앞 토큰에 들러붙게 둔다. 그러면 세그먼트가 안 갈리고, "--body 탐색을
# 매칭된 gh 호출과 같은 셸 세그먼트로 좁힌다"는 이 모듈의 국소성 설계가
# 무력화된다. 형제 게이트(check_git_state)는 같은 결함을 실사고로 겪고 고쳤다.

def test_glued_semicolon_does_not_swallow_next_token(tmp_path):
    """`;`가 공백 없이 붙어도 경로가 온전해야 한다(오탐 방지)."""
    p = tmp_path / "body.md"
    p.write_text(_SAMPLE_BODY, encoding="utf-8")
    body, reason = ghc.extract_body_from_command(
        f"gh pr create --title t --body-file {p};echo done"
    )
    assert reason is None
    assert body == _SAMPLE_BODY


def test_glued_semicolon_does_not_leak_next_command_body(tmp_path):
    """뒤 명령의 본문을 앞 gh 호출의 것으로 채택해서는 아니 된다."""
    other = tmp_path / "other.md"
    other.write_text("무관한 본문\n", encoding="utf-8")
    body, reason = ghc.extract_body_from_command(
        f"gh pr create --title t;gh pr comment 1 --body-file {other}"
    )
    assert body is None
    assert reason is not None


def test_ampersand_does_not_leak_next_command_body(tmp_path):
    """단일 `&`도 세그먼트 경계다 — 뒤 명령의 본문이 새어서는 아니 된다."""
    other = tmp_path / "other.md"
    other.write_text("무관한 본문\n", encoding="utf-8")
    body, reason = ghc.extract_body_from_command(
        f"gh pr create --title t & gh pr comment 1 --body-file {other}"
    )
    assert body is None
    assert reason is not None
