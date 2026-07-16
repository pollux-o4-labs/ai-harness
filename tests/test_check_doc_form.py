#!/usr/bin/env python3
# BLUF: check_doc_form의 폼-정본성·줄/BLUF 예산·표행/코드펜스 면제·화이트리스트·유형판정 fallback·pre-commit 배선 자기잠금방지를 무DB·무LLM으로 검증.
"""tests/test_check_doc_form.py — 문서 폼 게이트 단위테스트(무DB·무LLM).

scripts를 import하기 위해 repo 루트의 scripts 디렉토리를 sys.path에 얹는다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_doc_form as cdf  # noqa: E402


# --- 헬퍼 -------------------------------------------------------------------
#
# doc_type()은 순수 문자열 판정(path.parts)이라 cwd와 무관하다 — 문서 경로는
# "docs/..."로 시작하는 상대경로면 된다. 반면 FORM_DIR은 (버그3 수정 후) 스크립트
# 자신의 위치에 앵커링되어 cwd와 무관하다 — 합성 폼으로 테스트하려면 cdf.FORM_DIR
# 자체를 monkeypatch해야 실제로 읽힌다(fake_repo 픽스처가 담당).

def _write_form(name: str, *, max_lines: int | None = None,
                 line_chars: int | None = None, bluf_chars: int | None = None) -> None:
    """합성 폼 파일을 cdf.FORM_DIR(현재 monkeypatch된 위치)에 쓴다. 실제 폼과
    같은 문구 관례("N줄 · 산문 한 줄 N자 · BLUF 한 줄 N자")를 쓴다 — "이하"
    접미사 없이(실제 폼 문구가 그렇다, 버그1)."""
    parts = []
    if max_lines is not None:
        parts.append(f"{max_lines}줄")
    if line_chars is not None:
        parts.append(f"산문 한 줄 {line_chars}자")
    if bluf_chars is not None:
        parts.append(f"BLUF 한 줄 {bluf_chars}자")
    cdf.FORM_DIR.mkdir(parents=True, exist_ok=True)
    (cdf.FORM_DIR / f"{name}.md").write_text(
        "<!-- 예산: " + " · ".join(parts) + "(마커 제외) -->\n", encoding="utf-8"
    )


def _write_doc(rel: str, content: str) -> Path:
    p = Path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """빈 임시 저장소로 cwd를 옮기고, FORM_DIR도 같은 임시 트리 밑으로
    monkeypatch한다. 문서 경로(doc_type 판정용)는 cwd 기준 상대경로면 되지만,
    합성 폼은 FORM_DIR을 직접 옮기지 않으면 실제 repo의 진짜 폼을 보게 된다
    (버그3 수정으로 FORM_DIR이 더는 cwd를 안 따라가므로)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cdf, "FORM_DIR", tmp_path / "docs" / "docs-format")


@pytest.fixture
def real_forms(fake_repo, monkeypatch):
    """진짜 저장소의 실제 docs/docs-format을 직접 가리킨다(읽기 전용이라 복사
    불필요) — 실제 예산(100줄·80자·100자)으로 검증하는 테스트용. cwd는 여전히
    fake_repo가 옮긴 무관한 임시 디렉터리 그대로다 — 이 자체가 버그3(FORM_DIR이
    CWD 상대였던 결함)의 직접 회귀 증거: cwd가 repo와 무관해도 FORM_DIR이
    스크립트 위치를 앵커로 옳게 찾아야 아래 테스트들이 통과한다."""
    monkeypatch.setattr(cdf, "FORM_DIR", _REPO_ROOT / "docs" / "docs-format")


# --- 제1성질: 폼이 정본이다(하드코딩 아님) ------------------------------------

def test_form_budget_is_canonical_not_hardcoded(fake_repo):
    """폼 파일의 수치를 바꾸면 검사기 판정이 따라 바뀐다 — 예산이 코드에
    하드코딩돼 있지 않다는 증명(이 설계의 핵심, 제일 중요한 테스트)."""
    _write_form("widget", line_chars=10)
    doc = _write_doc("docs/widget/x.md", "가" * 15 + "\n")

    assert cdf.check_file(doc) != []  # 예산 10자에 15자 줄 — 리젝

    _write_form("widget", line_chars=20)  # 같은 문서, 폼 수치만 올림
    assert cdf.check_file(doc) == []  # 이제 통과 — 판정이 폼을 따라갔다


# --- 버그3: FORM_DIR 경로 앵커 · 폼 부재 fail-closed --------------------------
#
# 감독이 직접 재현한 결함: FORM_DIR이 CWD 상대라 다른 디렉터리에서 실행하면
# 폼을 못 찾고, load_budgets가 빈 dict를 반환해 예산이 전부 None이 되어 검사를
# 통째로 건너뛰고 조용히 통과했다("위반이 없어서"가 아니라 "잴 자가 없어서").

def test_cwd_independent_verdict_regression(tmp_path, monkeypatch):
    """같은 파일, CWD만 달라도 같은 판정이 나와야 한다(이번 결함의 직접 회귀).
    FORM_DIR이 스크립트 자신의 위치를 앵커로 쓰면 무관한 CWD에서도 폼을 찾는다."""
    doc = tmp_path / "outside.md"
    doc.write_text(("가" * 200) + "\n", encoding="utf-8")

    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)  # repo와 전혀 무관한 CWD(FORM_DIR은 그대로 real)

    violations = cdf.check_file(doc)
    assert violations != []
    assert not any("예산을 하나도 못 뽑음" in v for v in violations)  # 자를 제대로 찾았다


def test_missing_form_dir_fails_closed_not_open(tmp_path, monkeypatch):
    """폼 디렉터리 자체가 없으면(FORM_DIR이 가리키는 곳이 깨졌거나 폼이 통째로
    안 배포됐거나) 조용히 통과가 아니라 큰 소리로 리젝해야 한다(fail-closed).
    검사기 자체의 부재(훅 래퍼가 fail-open으로 처리하는 층)와는 다른 층이다."""
    monkeypatch.setattr(cdf, "FORM_DIR", tmp_path / "nonexistent-forms")
    doc = tmp_path / "x.md"
    doc.write_text("아무 문서\n", encoding="utf-8")

    violations = cdf.check_file(doc)
    assert violations != []
    assert any("예산을 하나도 못 뽑음" in v for v in violations)


def test_empty_form_dir_fails_closed(tmp_path, monkeypatch):
    """폼 디렉터리는 있지만 전역 폴백(rules.md)이 없으면 마찬가지로 리젝한다."""
    empty_dir = tmp_path / "docs-format"
    empty_dir.mkdir()
    monkeypatch.setattr(cdf, "FORM_DIR", empty_dir)
    doc = tmp_path / "x.md"
    doc.write_text("아무 문서\n", encoding="utf-8")

    violations = cdf.check_file(doc)
    assert violations != []
    assert any("예산을 하나도 못 뽑음" in v for v in violations)


# --- 문서 100줄 예산 ---------------------------------------------------------

def test_over_line_budget_rejected(real_forms):
    doc = _write_doc("docs/rules/x.md", "x\n" * 101)
    violations = cdf.check_file(doc)
    assert any("101줄 > 100줄" in v for v in violations)


def test_within_line_budget_passes(real_forms):
    """경계 포함: 정확히 100줄(+표준 후행 개행)은 통과해야 한다.

    회귀(버그2): split("\\n")은 후행 개행이 있는 표준 파일에서 팬텀 빈 줄을
    하나 더 세어 실제 100줄 문서를 101줄로 오탐 리젝했다. splitlines()로 고쳤다.
    """
    doc = _write_doc("docs/rules/x.md", "x\n" * 100)
    assert cdf.check_file(doc) == []


def test_empty_file_passes_without_crash(real_forms):
    doc = _write_doc("docs/rules/x.md", "")
    assert cdf.check_file(doc) == []


# --- 산문 한 줄 80자 예산 -----------------------------------------------------

def test_prose_over_char_budget_rejected_with_file_and_line(real_forms):
    doc = _write_doc("docs/rules/x.md", "짧다\n" + ("가" * 81) + "\n짧다\n")
    violations = cdf.check_file(doc)
    assert any(f"{doc}:2:" in v for v in violations)
    assert any("81자 > 80자" in v for v in violations)


def test_prose_char_budget_boundary_is_inclusive(real_forms):
    """정확히 80자는 통과 — 경계에서 한 글자 차이로 리젝되면 안 된다."""
    doc = _write_doc("docs/rules/x.md", ("가" * 80) + "\n")
    assert cdf.check_file(doc) == []


# --- 한 줄 한 문장(문장 종결 마침표) — 80자와 별개 축 -------------------------

def test_multiple_sentences_in_one_line_rejected(real_forms):
    """한 줄에 문장 종결 '. '가 있으면 여러 문장이므로 리젝한다."""
    doc = _write_doc("docs/rules/x.md", "짧다\n한 문장이다. 두 번째가 붙었다.\n짧다\n")
    violations = cdf.check_file(doc)
    assert any("문장이 여럿" in v for v in violations)
    assert any(f"{doc}:2:" in v for v in violations)


def test_sentence_rule_excludes_decimals_paths_numbers(real_forms):
    """오탐 방지: 소수(0.85)·코드 경로(config.py)·번호 리스트(1. )·줄끝
    마침표는 문장 종결이 아니다 — 마침표 앞이 숫자거나 뒤가 공백이 아니면
    안 걸린다."""
    body = (
        "소수 0.85 값을 쓴다\n"
        "config.py 경로를 참조한다\n"
        "1. 번호 리스트 항목이다\n"
        "한 문장이 줄 끝에서 끝난다.\n"
    )
    doc = _write_doc("docs/rules/x.md", body)
    sentence_violations = [v for v in cdf.check_file(doc) if "문장이 여럿" in v]
    assert sentence_violations == []


def test_heading_exempt_from_sentence_rule(real_forms):
    """헤딩(`## A. 환경`)의 `A.`는 문장 끝이 아니다 — 구조 라벨이라 문장
    규칙에서 뺀다. 숫자 라벨과 달리 문자 라벨은 앞자리 숫자 배제로 안 걸러진다."""
    body = "## A. 환경/인프라\n짧다\n### B. 문서 구조\n짧다\n"
    doc = _write_doc("docs/rules/x.md", body)
    sentence_violations = [v for v in cdf.check_file(doc) if "문장이 여럿" in v]
    assert sentence_violations == []


def test_heading_still_bound_by_line_length(real_forms):
    """헤딩은 문장 규칙만 면제다 — 길이 예산은 그대로 진다(라벨은 짧아야 한다)."""
    doc = _write_doc("docs/rules/x.md", "## " + ("가" * 90) + "\n")
    length_violations = [v for v in cdf.check_file(doc) if "80자" in v]
    assert length_violations != []


# --- 좌표(줄번호) 게이트 — 현재상태 문서만 -----------------------------------

def test_coordinate_rejected_in_features(real_forms):
    """현재상태 문서(features)의 손으로 친 줄번호 좌표는 리젝된다."""
    doc = _write_doc("docs/features/x.md", "짧다\n소스는 `config.py:168`이다\n")
    coord = [v for v in cdf.check_file(doc) if "좌표" in v]
    assert coord != []
    assert any("config.py:168" in v for v in coord)


def test_coordinate_rejected_in_rules_current_state(real_forms):
    """현재상태 문서는 features만이 아니다 — rules도 좌표를 리젝한다(denylist)."""
    doc = _write_doc("docs/rules/x.md", "짧다\n소스는 `config.py:168`이다\n")
    assert [v for v in cdf.check_file(doc) if "좌표" in v] != []


def test_coordinate_exempt_in_dated_records(real_forms):
    """날짜 박힌 기록(adr·history·review·test)의 줄번호는 그 시점 기록이라 면제."""
    for rel in ("docs/adr/x.md", "docs/history/B-x.md",
                "docs/review/x.md", "docs/test/x.md"):
        doc = _write_doc(rel, "짧다\n결정 시점 `graph.py:347`\n")
        assert [v for v in cdf.check_file(doc) if "좌표" in v] == []


def test_coordinate_gate_ignores_urls_timestamps_symbols(real_forms):
    """오탐 방지: URL·타임스탬프·심볼(::)·SHA경로는 좌표가 아니다."""
    body = (
        "서버는 `localhost:8765`에 뜬다\n"
        "로그 시각 16:55에 찍혔다\n"
        "진입은 `cli.py::main`이다\n"
        "확인 `git show abc123:docs/x.md`\n"
    )
    doc = _write_doc("docs/features/x.md", body)
    assert [v for v in cdf.check_file(doc) if "좌표" in v] == []


# --- diff 스코프(--staged): 손댄 줄만 강제 -----------------------------------

def _rungit(*args):
    # 주의: 이 파일 하단에 `_git(repo, *args)`가 따로 있어 이름이 겹친다.
    # 파이썬은 나중 정의로 덮으므로 CWD 기준 헬퍼는 다른 이름을 쓴다.
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _seed_repo(rel, content):
    """tmp cwd에 git 레포를 만들고 파일을 커밋한다(diff base 확보)."""
    _rungit("init", "-q")
    _rungit("config", "user.email", "t@t")
    _rungit("config", "user.name", "t")
    doc = _write_doc(rel, content)
    _rungit("add", rel)
    _rungit("commit", "-qm", "seed")
    return doc


def test_staged_scopes_to_changed_lines_not_whole_file(real_forms):
    """진행형의 핵심: 기존 위반 줄은 유예하고 이번에 추가/변경한 줄만 리젝한다.
    한 줄 고치려 문서 전체 재정합을 강요하던 캐스케이드를 끊는다."""
    long = "가" * 90  # 80자 초과
    doc = _seed_repo("docs/rules/x.md", f"짧다\n{long}\n짧다\n")
    doc.write_text(f"짧다\n{long}\n{long}\n짧다\n", encoding="utf-8")  # 새 위반 줄 삽입
    _rungit("add", "docs/rules/x.md")
    staged = cdf.check_staged(doc)
    assert len(staged) == 1                    # 이번에 추가한 줄만
    assert "80자" in staged[0]
    assert len([v for v in cdf.check_file(doc) if "80자" in v]) == 2  # 전체는 둘 다 본다


def test_staged_passes_when_fixing_unrelated_line(real_forms):
    """기존 위반 문서에서 위반과 무관한 한 줄만 고치면(새 위반 0) 통과한다."""
    long = "가" * 90
    doc = _seed_repo("docs/rules/x.md", f"원래 짧다\n{long}\n짧다\n")
    doc.write_text(f"고친 짧은 줄\n{long}\n짧다\n", encoding="utf-8")  # 1번째 줄만 수정
    _rungit("add", "docs/rules/x.md")
    assert cdf.check_staged(doc) == []         # 기존 LONG 줄은 유예


def test_staged_new_file_fully_checked(real_forms):
    """새 파일은 모든 줄이 '추가'라 전량 검사된다(신규는 완전 준수)."""
    long = "가" * 90
    _rungit("init", "-q")
    _rungit("config", "user.email", "t@t")
    _rungit("config", "user.name", "t")
    doc = _write_doc("docs/rules/new.md", f"짧다\n{long}\n")
    _rungit("add", "docs/rules/new.md")
    assert any("80자" in v for v in cdf.check_staged(doc))


def test_staged_linecount_only_on_net_add(fake_repo):
    """줄수 초과는 이번 변경이 순증(추가>삭제)일 때만 — 치환만이면 유예."""
    _write_form("rules", max_lines=3, line_chars=80)
    doc = _seed_repo("docs/rules/x.md", "a\nb\nc\nd\n")  # 4줄 = 예산 3 초과
    doc.write_text("a2\nb\nc\nd\n", encoding="utf-8")   # 순증 0(치환)
    _rungit("add", "docs/rules/x.md")
    assert not any("비대" in v for v in cdf.check_staged(doc))


def test_staged_reads_index_not_worktree(real_forms):
    """스테이징 후 워킹트리를 더 고쳐 줄번호가 어긋나도, 커밋될 내용(인덱스)의
    위반을 잡는다. 워킹트리를 읽으면 좌표계가 갈라져 fail-open(적대검증 재현)."""
    long = "가" * 90
    doc = _seed_repo("docs/rules/x.md", "짧다\n짧다\n")
    doc.write_text(f"짧다\n{long}\n짧다\n", encoding="utf-8")  # 인덱스: LONG=2번째 줄
    _rungit("add", "docs/rules/x.md")
    # 재-스테이징 없이 워킹트리 앞에 2줄 추가 → 워킹트리에선 LONG이 4번째 줄로 밀림
    doc.write_text(f"머리\n앞\n짧다\n{long}\n짧다\n", encoding="utf-8")
    staged = cdf.check_staged(doc)
    # 인덱스(커밋될 내용)의 LONG 위반을 잡아야 한다 — 워킹트리 좌표로 놓치면 fail-open
    assert any("80자" in v for v in staged)


def test_staged_line_delta_counts_dash_content(real_forms):
    """삭제 콘텐츠가 `---`(수평선)이어도 삭제로 센다 — 파일헤더 `--- a/path`와
    콘텐츠를 접두어로 구별하면 언더카운트(적대검증 버그1)."""
    doc = _seed_repo("docs/rules/x.md", "머리\n---\n본문\n")
    doc.write_text("본문\n", encoding="utf-8")  # '머리'와 '---' 2줄 순삭제
    _rungit("add", "docs/rules/x.md")
    _added, removed = cdf.staged_line_delta(doc)
    assert removed == 2  # '---'도 삭제로 세야(접두어 아니라 위치로 판정)


def test_staged_added_line_starting_with_plus_is_checked(real_forms):
    """새로 친 위반 줄의 콘텐츠가 `++`로 시작해도(diff에서 `+++`) 검사한다 —
    접두어 판정이면 false negative로 새는 축(적대검증 버그1)."""
    doc = _seed_repo("docs/rules/x.md", "짧다\n")
    doc.write_text("짧다\n" + "++" + "가" * 90 + "\n", encoding="utf-8")  # 92자, ++시작
    _rungit("add", "docs/rules/x.md")
    assert any("80자" in v for v in cdf.check_staged(doc))


def test_staged_rename_not_bypassed(real_forms):
    """개명+작은 편집을 한 커밋에 해도 게이트가 통째로 새면 안 된다(적대검증 버그2).
    ACM 필터는 R(개명)을 빼 개명 파일이 우회됐다 — ACMR + 옛/새 경로로 잡는다.
    편집이 작아야 git이 rename으로 판정(바이트 유사도)하므로 짧은 좌표 위반을 쓴다."""
    base = "".join(f"줄{i}\n" for i in range(60))  # 큰 파일 → 유사도 높아 R 판정
    _seed_repo("docs/features/old.md", base)  # features = 좌표 게이트 대상
    _rungit("mv", "docs/features/old.md", "docs/features/new.md")
    Path("docs/features/new.md").write_text(base + "소스 `config.py:5`.\n", encoding="utf-8")
    _rungit("add", "docs/features/new.md")
    files = cdf.staged_files()
    md = [(n, o) for n, o in files if n.as_posix().endswith("new.md")]
    assert md, "개명 파일이 staged 목록에 있어야 한다(ACMR)"
    new, old = md[0]
    assert old is not None and old.as_posix().endswith("old.md")  # rename 감지·옛경로 확보
    assert any("좌표" in v for v in cdf.check_staged(new, old))  # 새 좌표 위반 잡힘


# --- 표 행·코드펜스 면제 ------------------------------------------------------

def test_table_row_exempt_from_line_length(real_forms):
    long_row = "|" + "가" * 90 + "|\n"
    doc = _write_doc("docs/rules/x.md", long_row)
    assert cdf.check_file(doc) == []


def test_line_starting_with_pipe_but_not_real_table_is_still_exempt(real_forms):
    """설계상 '|'로 시작하면 무조건 표 행 취급한다 — 진짜 마크다운 표(헤더
    구분행 등)인지는 안 따진다(의도된 단순 휴리스틱, 팀 브리핑 그대로)."""
    not_really_a_table = "|" + "그냥 파이프로 시작하는 줄일 뿐이다 " * 5 + "\n"
    doc = _write_doc("docs/rules/x.md", not_really_a_table)
    assert cdf.check_file(doc) == []


def test_code_fence_content_exempt_from_line_length(real_forms):
    content = "```\n" + ("x" * 90) + "\n```\n"
    doc = _write_doc("docs/rules/x.md", content)
    assert cdf.check_file(doc) == []


def test_fence_toggle_reactivates_check_after_close(real_forms):
    """닫는 펜스 이후엔 검사가 다시 걸려야 한다 — 토글이 정확히 짝을 맞춘다."""
    content = "```\n" + ("x" * 90) + "\n```\n" + ("가" * 90) + "\n"
    doc = _write_doc("docs/rules/x.md", content)
    violations = cdf.check_file(doc)
    assert any(f"{doc}:4:" in v for v in violations)


def test_unclosed_fence_exempts_rest_of_file(real_forms):
    """펜스가 안 닫히면 토글이 다시 안 꺼져 이후 전부가 면제된다 — 현재
    토글 설계의 알려진 결과를 고정한다(수정 대상 아님, 팀 브리핑: 설계 불변)."""
    content = "```\n" + ("가" * 90) + "\n"  # 닫는 펜스 없음
    doc = _write_doc("docs/rules/x.md", content)
    assert cdf.check_file(doc) == []


# --- BLUF 한 줄 100자 예산 ----------------------------------------------------

def test_bluf_over_budget_rejected(real_forms):
    doc = _write_doc("docs/rules/x.md", "> **BLUF:** " + ("가" * 101) + "\n")
    violations = cdf.check_file(doc)
    assert any("BLUF" in v and "101자 > 100자" in v for v in violations)


def test_bluf_marker_prefix_not_counted(real_forms):
    """마커 `> **BLUF:** ` 자체 길이는 100자 예산에 안 들어간다 — 정확히
    100자 본문(마커 제외)은 통과해야 한다."""
    doc = _write_doc("docs/rules/x.md", "> **BLUF:** " + ("가" * 100) + "\n")
    assert cdf.check_file(doc) == []


# --- WHITELIST ---------------------------------------------------------------

def test_whitelisted_path_is_exempt(real_forms, monkeypatch):
    doc = _write_doc("docs/rules/x.md", ("가" * 200) + "\n")
    assert cdf.check_file(doc) != []  # 화이트리스트 전이면 리젝됨을 먼저 확인
    monkeypatch.setattr(cdf, "WHITELIST", frozenset({doc.as_posix()}))
    assert cdf.check_file(doc) == []


def test_whitelist_defaults_to_empty():
    """WHITELIST는 비어 있는 게 기본 — 면제 문서 없음(의도된 상태, 원칙 5).
    누군가 조용히 항목을 미리 채워두면 이 테스트가 깨진다."""
    assert cdf.WHITELIST == frozenset()


# --- 유형 판정 · 폼 없는 유형의 fallback --------------------------------------

def test_type_without_own_form_falls_back_to_global(real_forms):
    doc = _write_doc("docs/guide/x.md", ("가" * 81) + "\n")
    assert cdf.doc_type(doc) == "guide"
    assert cdf.load_budgets("guide") == {}  # guide.md 폼 자체가 없다
    violations = cdf.check_file(doc)
    assert any("81자 > 80자" in v for v in violations)  # rules.md 폴백이 걸었다


def test_type_specific_form_overrides_fallback(fake_repo):
    """유형 전용 폼이 있으면 그 수치가 이긴다 — 폴백(_GLOBAL_FORM=rules)보다
    우선한다."""
    _write_form("rules", line_chars=80)   # 전역 폴백(느슨)
    _write_form("widget", line_chars=10)  # 유형 전용(빡빡)

    doc = _write_doc("docs/widget/x.md", ("가" * 15) + "\n")
    violations = cdf.check_file(doc)
    assert any("15자 > 10자" in v for v in violations)  # 폴백(80) 아니라 유형(10)


# --- main() exit code ---------------------------------------------------------

def test_main_with_no_targets_returns_zero():
    assert cdf.main([]) == 0


def test_main_exit_zero_when_clean(real_forms):
    doc = _write_doc("docs/rules/x.md", "짧다\n")
    assert cdf.main([str(doc)]) == 0


def test_main_exit_one_when_violations(real_forms):
    doc = _write_doc("docs/rules/x.md", ("가" * 200) + "\n")
    assert cdf.main([str(doc)]) == 1


# --- --staged 모드 ------------------------------------------------------------
#
# staged_markdown()은 실제 git 인덱스(git diff --cached)를 읽으므로 유닛테스트가
# 아니라 실제 git repo가 필요하다.

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")  # 호스트 전역설정 격리


def _copy_forms(repo: Path) -> None:
    shutil.copytree(_REPO_ROOT / "docs" / "docs-format", repo / "docs" / "docs-format")


def _run_staged(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "check_doc_form.py"), "--staged"],
        cwd=repo, capture_output=True, text=True,
    )


def test_staged_with_zero_staged_md_passes(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "note.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "note.txt")
    result = _run_staged(repo)
    assert result.returncode == 0


def test_staged_only_checks_staged_not_unstaged_md(tmp_path):
    """스테이징 안 된(기존 위반) 문서는 안 걸린다 — 손대는 문서부터 폼에
    맞춘다는 설계(안 그러면 기존 위반 문서 전부가 커밋을 막는다)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _copy_forms(repo)
    (repo / "docs" / "rules").mkdir(parents=True)
    (repo / "docs" / "rules" / "good.md").write_text("짧다\n", encoding="utf-8")
    _git(repo, "add", "docs/rules/good.md")
    # bad.md는 위반이지만 스테이징 안 됨(untracked로 방치)
    (repo / "docs" / "rules" / "bad.md").write_text(("가" * 200) + "\n", encoding="utf-8")

    result = _run_staged(repo)
    assert result.returncode == 0


def test_staged_rejects_when_staged_md_violates(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _copy_forms(repo)
    (repo / "docs" / "rules").mkdir(parents=True)
    (repo / "docs" / "rules" / "bad.md").write_text(("가" * 200) + "\n", encoding="utf-8")
    _git(repo, "add", "docs/rules/bad.md")

    result = _run_staged(repo)
    assert result.returncode == 1


# --- pre-commit 배선(git 훅) 자체 회귀 ----------------------------------------
#
# 유닛테스트가 아니라 **커밋되는 hooks/pre-commit 그 자체**를 실행한다 —
# check_pr_body의 settings.json 쉘 한 줄과 동형 위험: 검사기 부재 시 훅이
# 죽으면 저장소의 모든 커밋이 막힌다(게이트가 자기 자신을 잠금, ADR 0029 조건3).

def _install_precommit_hook(repo: Path) -> None:
    """실제 커밋되는 hooks/pre-commit을 .git/hooks/로 복사·chmod +x —
    scripts/install_hooks.py가 하는 것과 동일한 조작을 그대로 실행한다."""
    dst = repo / ".git" / "hooks" / "pre-commit"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_REPO_ROOT / "hooks" / "pre-commit", dst)
    dst.chmod(dst.stat().st_mode | 0o111)


def _install_checker(repo: Path) -> None:
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(_REPO_ROOT / "scripts" / "check_doc_form.py", repo / "scripts" / "check_doc_form.py")
    _copy_forms(repo)


def _commit_doc(repo: Path, rel_path: str, content: str) -> subprocess.CompletedProcess:
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    return _git(repo, "commit", "-q", "-m", "test")


@pytest.fixture
def wired_repo(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _install_precommit_hook(repo)
    return repo


def test_wired_hook_blocks_bad_doc(wired_repo):
    _install_checker(wired_repo)
    result = _commit_doc(wired_repo, "docs/rules/x.md", ("가" * 90) + "\n")
    assert result.returncode != 0
    assert "리젝" in result.stdout + result.stderr


def test_wired_hook_allows_good_doc(wired_repo):
    _install_checker(wired_repo)
    result = _commit_doc(wired_repo, "docs/rules/x.md", "짧다\n")
    assert result.returncode == 0


def test_wired_hook_allows_unrelated_non_md_commit(wired_repo):
    _install_checker(wired_repo)
    result = _commit_doc(wired_repo, "README.txt", "hello\n")
    assert result.returncode == 0


def test_wired_hook_does_not_lock_repo_when_checker_absent(wired_repo):
    """검사기가 없으면 게이트는 꺼지되 저장소를 잠그지는 않는다.

    check_pr_body의 동명 회귀(test_wired_hook_does_not_lock_repo_when_checker_absent)와
    같은 성질: 파일 부재는 git에서 보이는 문제이므로, 전 커밋을 막는 것보다
    게이트가 조용히 꺼지는 편이 덜 해롭다. scripts/check_doc_form.py를
    설치하지 않은 채(부재 상태) 위반감 문서를 커밋해도 통과해야 한다.
    """
    result = _commit_doc(wired_repo, "docs/rules/x.md", ("가" * 200) + "\n")
    assert result.returncode == 0
