# BLUF: check_pr_body의 섹션 필수·섹션별 예산·은어 풀이·gh 명령 본문추출·훅 exit코드를 무DB·무LLM으로 검증.
"""tests/test_check_pr_body.py — PR 본문 게이트 단위테스트(무DB·무LLM).

scripts를 import하기 위해 repo 루트의 scripts 디렉토리를 sys.path에 얹는다.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_pr_body as cpb  # noqa: E402

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
- `docs/rules/09-pr-body-structure.md` — 조문(수치는 스크립트가 정본이라 재서술 안 함)

## 범위 밖

서버측 백스톱(GitHub Actions)은 안 넣음 — 새는 사례 관측되면 그때.

## 검증

`uv run pytest tests/test_check_pr_body.py` → exit 0, 커밋 산출물 기준.

## 확인

- [x] 가독성을 높이는 검수를 진행했다
  - [x] 과한 내부 은어 사용 검수했다
  - [x] 비전문가, 제3자도 쉽게 이해할 수 있도록 작성되었는지 검토했다
- [x] 이 변경이 다른 문서를 낡게 하지 않았는지 검토했다
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

def test_jargon_without_gloss_rejected():
    body = GOOD_BODY.replace("커밋 산출물 기준.", "폴백 경로도 확인.")
    assert any("'폴백'에 풀이가 없음" in v for v in cpb.check_pr_body(body))


def test_jargon_with_gloss_passes():
    body = GOOD_BODY.replace(
        "커밋 산출물 기준.", "폴백(원문까지 훑는 최후 경로) 확인."
    )
    assert cpb.check_pr_body(body) == []


def test_jargon_in_code_is_ignored():
    """명령어 안의 용어는 산문이 아니다 — 풀이를 요구하지 않는다."""
    body = GOOD_BODY.replace("커밋 산출물 기준.", "`vgo status`로 워터마크 확인.")
    assert any("'워터마크'" in v for v in cpb.check_pr_body(body))
    body_fenced = GOOD_BODY.replace("커밋 산출물 기준.", "`vgo status --워터마크`")
    assert cpb.check_pr_body(body_fenced) == []


def test_new_repeat_offender_jargon_rejected():
    """관측된 상습범(fail-open·캐스케이드)도 풀이 없으면 리젝 — 게이트 세션에서
    풀이 없이 반복 샌 것을 규칙 09대로 목록에 보강했다(목록은 바닥이지 증명 아님)."""
    for term in ("fail-open", "캐스케이드"):
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
# org `.github` 레포의 공용 템플릿이 이미 13개 레포에 `변경 유형`·`관련 이슈`를
# 뿌리고 있었는데, 게이트는 그 둘을 "템플릿에 없는 섹션"으로 리젝했다 — 공용
# 템플릿으로 연 PR을 `gh pr merge`가 막는 상태였다(본문을 gh pr view로 끌어와
# 검사하므로 웹에서 연 PR도 걸린다). 아래는 그 통합의 회귀 방지다.

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


def test_exempt_section_ignores_length():
    """면제 섹션이 아무리 길어도 예산 위반이 나오면 안 된다."""
    body = GOOD_BODY.replace("Closes #1", "가" * 5000)
    assert not any("'## 관련 이슈'" in v for v in cpb.check_pr_body(body))


def test_exempt_section_excluded_from_budget_total(capsys):
    """면제 섹션은 총계에도 안 들어간다 — `확인`과 같은 이유."""
    body = GOOD_BODY.replace("Closes #1", "가" * 5000)
    cpb._report(["dummy"], body)
    reported = capsys.readouterr().err
    prose_only = sum(
        cpb.measure(cpb.parse_sections(body).get(n, "")) for n in cpb.SECTION_BUDGETS
    )
    assert f"총 {prose_only}자" in reported
    assert "5000" not in reported


def test_unknown_section_still_rejected():
    """면제 목록을 열었다고 아무 섹션이나 통과하면 게이트가 아니다."""
    body = GOOD_BODY.replace("## 관련 이슈", "## 아무거나")
    assert any("템플릿에 없는 섹션" in v and "아무거나" in v
               for v in cpb.check_pr_body(body))


# --- create/merge 분리: 체크리스트 완료는 머지에서만 -------------------------

def test_create_mode_allows_unchecked_checklist():
    """PR 생성(리뷰 요청) 시점엔 확인 체크리스트가 미체크여도 통과 — 형식만 강제."""
    body = GOOD_BODY.replace("[x]", "[ ]")  # 모든 체크 해제
    assert cpb.check_pr_body(body, require_checklist_complete=False) == []


def test_create_mode_still_enforces_format():
    """create여도 형식(은어 등)은 강제된다 — 체크리스트 완료만 유예."""
    body = GOOD_BODY.replace("[x]", "[ ]").replace("커밋 산출물 기준.", "폴백 확인.")
    v = cpb.check_pr_body(body, require_checklist_complete=False)
    assert any("'폴백'" in x for x in v)  # 은어는 여전히 잡힘


def test_create_mode_still_requires_checklist_section():
    """create여도 확인 절 자체는 있어야 한다 — 리뷰어가 채울 자리."""
    body = GOOD_BODY.split("## 확인")[0]
    v = cpb.check_pr_body(body, require_checklist_complete=False)
    assert any("'## 확인' 없음" in x for x in v)


def test_merge_mode_requires_all_checked():
    """머지 시점(기본 True)엔 미체크 항목이 있으면 리젝."""
    body = GOOD_BODY.replace("[x] 가독성", "[ ] 가독성")
    assert any("체크 안 됨" in x for x in cpb.check_pr_body(body))  # 기본=완료요구


def test_checkbox_is_self_report_not_evidence():
    """체크박스가 강제하는 것은 글자 'x' 하나뿐임을 고정한다(원칙 2).

    이 테스트가 통과한다는 사실 자체가 체크박스의 한계다 — 본문이 서사·은어
    범벅이어도 체크 한 글자로 이 항목은 통과한다. 실물을 재는 것은 섹션·예산·
    풀이 검사이고, 이 항목은 리뷰어에게 넘기는 자기신고에 지나지 않는다.
    """
    lying = GOOD_BODY.replace(
        "PR 본문에 섹션·분량·용어풀이 게이트를 건다.",
        "이 저장소를 모르는 사람은 절대 못 읽는 문장이다.",
    )
    assert cpb.check_checklist(cpb.parse_sections(lying)) == []
    # 실물을 재는 검사(예산·은어)는 여전히 살아 있다 — 체크박스가 그걸 못 끈다.
    assert cpb.check_jargon("## 요약\n\nL2 갱신\n") != []


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
# "머지는 사장 몫 — 감독·구현자는 머지하지 않는다"(docs/handoff/2-now-state.md)를
# 처음 기계로 강제하는 절. 본문은 명령 인자가 아니라 `gh pr view --json body`
# 능동 조회로 얻으므로, 실 gh CLI·네트워크·인증 없이 테스트하려면
# subprocess.run 또는 cpb._fetch_pr_body를 스텁한다.

def _stub_fetch(monkeypatch, *, body: str | None = None, reason: str | None = None):
    monkeypatch.setattr(cpb, "_fetch_pr_body", lambda identifier: (body, reason))


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
    monkeypatch.setattr(
        cpb, "_fetch_pr_body",
        lambda identifier: (captured.setdefault("id", identifier), (GOOD_BODY, None))[1],
    )
    cpb.extract_body_from_merge_command("gh pr merge 42 --squash")
    assert captured["id"] == "42"


def test_extract_body_from_merge_omitted_identifier_passes_none(monkeypatch):
    """PR 번호 생략(현재 브랜치 추론) — gh pr view에 식별자 없이 넘어가야 한다."""
    captured: dict[str, str | None] = {}
    monkeypatch.setattr(
        cpb, "_fetch_pr_body",
        lambda identifier: (captured.setdefault("id", identifier), (GOOD_BODY, None))[1],
    )
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
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"body": GOOD_BODY}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cpb._fetch_pr_body("42") == (GOOD_BODY, None)
    assert calls["cmd"] == ["gh", "pr", "view", "42", "--json", "body"]


def test_fetch_pr_body_no_identifier_omits_arg(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"body": "x"}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cpb._fetch_pr_body(None)
    assert calls["cmd"] == ["gh", "pr", "view", "--json", "body"]


def test_fetch_pr_body_gh_failure_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no pull requests found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body, reason = cpb._fetch_pr_body("999")
    assert body is None
    assert "못 들여다봄" in reason


def test_fetch_pr_body_bad_json_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body, reason = cpb._fetch_pr_body("42")
    assert body is None and reason is not None


def test_fetch_pr_body_empty_body_is_fail_closed(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"body": ""}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body, reason = cpb._fetch_pr_body("42")
    assert body is None and reason is not None


def test_fetch_pr_body_gh_binary_missing_is_fail_closed(monkeypatch):
    """gh 자체가 없어도(OSError) 크래시 대신 fail-closed 리젝 사유를 낸다."""
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body, reason = cpb._fetch_pr_body("42")
    assert body is None and reason is not None


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
        for h in m["hooks"] if "check_pr_body" in h.get("command", "")
    ]
    assert len(commands) == 1, f"Bash용 check_pr_body 훅이 1개가 아님: {commands}"
    return commands[0]


def _run_wired_hook(command: str, project_dir: Path) -> int:
    """훅 래퍼를 실제 sh로 실행하고 종료코드를 돌려준다."""
    return subprocess.run(
        ["sh", "-c", _hook_command()],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project_dir)},
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
    파일 부재는 git에서 보이는 문제이므로, 전 명령을 막는 것보다 게이트가
    조용히 꺼지는 편이 덜 해롭다.
    """
    assert _run_wired_hook("git status", tmp_path) == 0


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

def _make_fake_gh(tmp_path: Path, response_body: str) -> Path:
    """`gh pr view ... --json body` 호출에 고정 JSON을 돌려주는 가짜 gh.
    인자를 안 가리고 항상 같은 응답을 낸다 — 배선 자체 검증용이라 이걸로 충분."""
    payload = tmp_path / "gh_response.json"
    payload.write_text(json.dumps({"body": response_body}), encoding="utf-8")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(f'#!/usr/bin/env bash\ncat "{payload}"\n', encoding="utf-8")
    fake_gh.chmod(0o755)
    return tmp_path


def _run_wired_hook_with_fake_gh(command: str, fake_gh_dir: Path) -> int:
    return subprocess.run(
        ["sh", "-c", _hook_command()],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True,
        env={"PATH": f"{fake_gh_dir}:/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(_REPO_ROOT)},
    ).returncode


def test_wired_hook_blocks_merge_with_bad_body(tmp_path):
    fake_gh_dir = _make_fake_gh(tmp_path, "## 요약\n\n서사\n")
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 2


def test_wired_hook_allows_merge_with_good_body(tmp_path):
    fake_gh_dir = _make_fake_gh(tmp_path, GOOD_BODY)
    assert _run_wired_hook_with_fake_gh("gh pr merge 42", fake_gh_dir) == 0
