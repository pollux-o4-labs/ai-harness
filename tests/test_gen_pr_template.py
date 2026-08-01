# BLUF: gen_pr_template의 REQUIRED_CHECKS 렌더·계층 재현·--check 드리프트 감시·check_pr_body 교차검증을 검증.
"""tests/test_gen_pr_template.py — PR 템플릿 생성기 단위테스트.

DB도 LLM(언어모델)도 안 쓴다 — 순수 문자열 생성·비교라 어디서 돌려도 같은
결과다.
"""
from __future__ import annotations

from pathlib import Path

import ai_harness.check_pr_body as cpb
import ai_harness.gen_pr_template as gpt

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --- 렌더 내용 -----------------------------------------------------------------


def test_generated_template_matches_checked_in_file():
    """생성물은 저장소에 이미 있는 `.github/PULL_REQUEST_TEMPLATE.md`와
    바이트 동일해야 한다 — 다르면 골격 상수가 실제 템플릿과 어긋난 것."""
    checked_in = (_REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    assert gpt.render() == checked_in


def test_generated_contains_every_required_check_verbatim():
    """REQUIRED_CHECKS 각 항목 텍스트가 생성물에 그대로 있다 — 재서술 없음."""
    generated = gpt.render()
    for item in cpb.REQUIRED_CHECKS:
        assert item in generated, f"REQUIRED_CHECKS 항목 누락: {item}"


def test_checklist_hierarchy_indentation_is_reproduced():
    """계층의 자식 항목은 `  - [ ]`(2칸 들여쓰기)로, 부모는 `- [ ]`로 렌더된다."""
    lines = gpt._render_checklist()
    child_indices = {c for _, children in gpt._CHECK_HIERARCHY for c in children}
    parent_indices = {p for p, _ in gpt._CHECK_HIERARCHY}

    for parent_idx in parent_indices:
        text = cpb.REQUIRED_CHECKS[parent_idx]
        assert any(line == f"- [ ] {text}" for line in lines), f"부모 항목 형식 불일치: {text}"

    for child_idx in child_indices:
        text = cpb.REQUIRED_CHECKS[child_idx]
        assert any(line == f"  - [ ] {text}" for line in lines), f"자식 항목 들여쓰기 불일치: {text}"


def test_hierarchy_covers_every_required_check_exactly_once():
    """`_CHECK_HIERARCHY`가 REQUIRED_CHECKS의 모든 인덱스를 정확히 한 번씩 참조한다
    — 빠지면 템플릿에서 체크 항목이 사라지고, 중복되면 두 번 렌더된다."""
    covered: list[int] = []
    for parent_idx, child_idxs in gpt._CHECK_HIERARCHY:
        covered.append(parent_idx)
        covered.extend(child_idxs)
    assert sorted(covered) == list(range(len(cpb.REQUIRED_CHECKS)))


# --- check_pr_body와 교차검증 ---------------------------------------------------


def test_generated_checklist_section_passes_check_checklist():
    """생성된 `## 확인` 섹션이 check_pr_body의 체크리스트 검증을 통과한다
    (체크박스를 전부 [x]로 바꿔서 완료 상태를 흉내낸다)."""
    generated = gpt.render()
    checked = generated.replace("- [ ]", "- [x]")
    sections = cpb.parse_sections(checked)
    assert cpb.check_checklist(sections) == []


def test_generated_body_passes_full_check_pr_body_when_filled():
    """생성물의 골격에 최소 내용을 채우면 check_pr_body 전체 게이트를 통과한다
    — 섹션·예산·형태·체크리스트가 실제 검증기와 어긋나지 않음을 확인한다."""
    generated = gpt.render()
    checked = generated.replace("- [ ]", "- [x]")

    filled = (
        checked
        .replace(
            "<!-- 결론 한 줄(BLUF). 리뷰어가 diff를 열기 전에 알아야 할 것 하나. -->",
            "테스트용 요약 한 줄.",
        )
        .replace(
            '<!-- 무엇을 왜 바꿨나. 논쟁 가능한 판단은 근거까지 적는다 — -->\n'
            '<!-- "왜 이건 뺐나"가 리뷰에서 가장 먼저 나올 질문이면 그게 여기 들어갈 내용이다. -->',
            "테스트용 변경 내용.",
        )
        .replace(
            '<!-- 이번에 안 한 것과 그게 어디로 갔는지(이슈 번호). 없으면 "없음". -->\n'
            '<!-- 리뷰어의 "이건 왜 안 했나"를 선제 차단한다. -->',
            "없음",
        )
        .replace(
            "<!-- 다른 사람이 그대로 쳐서 재현할 수 있는 명령 + 종료코드. -->\n"
            "<!-- 무엇을 기준으로 쟀는지 밝힌다(워킹트리 아닌 커밋 산출물). -->",
            "`pytest` → exit 0.",
        )
    )
    violations = cpb.check_pr_body(filled, require_checklist_complete=True)
    assert violations == [], violations


# --- --check 드리프트 감시 -----------------------------------------------------


def test_no_arg_writes_generated_file(tmp_path):
    rc = gpt.main(["--root", str(tmp_path)])
    assert rc == 0
    target = tmp_path / gpt.TEMPLATE_RELPATH
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == gpt.render()


def test_check_passes_when_file_matches_generated(tmp_path):
    target = tmp_path / gpt.TEMPLATE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    gpt._write_lf(target, gpt.render())
    assert gpt.main(["--root", str(tmp_path), "--check"]) == 0


def test_check_fails_when_file_diverges(tmp_path):
    target = tmp_path / gpt.TEMPLATE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    gpt._write_lf(target, gpt.render().replace("가독성", "손으로바꾼텍스트"))
    assert gpt.main(["--root", str(tmp_path), "--check"]) != 0


def test_check_fails_when_file_missing(tmp_path):
    assert gpt.main(["--root", str(tmp_path), "--check"]) != 0


def test_check_does_not_write_file_on_mismatch(tmp_path):
    """드리프트를 감지해도 파일을 고치지 않는다 — --check는 순수 드라이런."""
    target = tmp_path / gpt.TEMPLATE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    stale = gpt.render().replace("가독성", "손으로바꾼텍스트")
    gpt._write_lf(target, stale)
    gpt.main(["--root", str(tmp_path), "--check"])
    assert target.read_text(encoding="utf-8") == stale


# --- 실제 저장소 드리프트 self-test(배선) --------------------------------------


def test_repo_template_has_no_drift():
    """체크인된 `.github/PULL_REQUEST_TEMPLATE.md`에 `--check`를 실제로 태워 exit 0인지
    — 드리프트 감시를 pytest에 배선한다(test_ruff_clean.py와 동형). REQUIRED_CHECKS 등
    정본이 바뀌면 여기서 fail해, 별도 CI·훅 없이 uv run pytest 한 번에 흡수된다."""
    assert gpt.main(["--check", "--root", str(_REPO_ROOT)]) == 0


def test_hierarchy_indices_pin_to_expected_items():
    """`_CHECK_HIERARCHY`의 부모·자식 인덱스 전부가 기대한 REQUIRED_CHECKS
    항목에 고정된다 — 커버리지 테스트(모든 인덱스가 정확히 한 번씩 등장)는 못
    잡는 '개수 동일, 형제 순서만 재정렬'을 이 앵커가 잡는다(재서술이 아니라
    각 슬롯이 여전히 그 의미의 항목인지 확인하는 앵커). 부모만이 아니라
    자식까지 정확한 (parent, children) 구조로 고정해야 형제 순서가 바뀌면
    렌더 의미가 조용히 달라지는 걸 잡는다."""
    assert gpt._CHECK_HIERARCHY == (
        (0, (1, 2)),
        (3, (4, 5, 6)),
        (7, ()),
        (8, ()),
    )
    assert cpb.REQUIRED_CHECKS[0].startswith("가독성")
    assert cpb.REQUIRED_CHECKS[1].startswith("과한 내부 은어")
    assert cpb.REQUIRED_CHECKS[2].startswith("비전문가")
    assert cpb.REQUIRED_CHECKS[3].startswith("이 변경이 다른 문서")
    assert cpb.REQUIRED_CHECKS[4].startswith("바꾼 값")
    assert cpb.REQUIRED_CHECKS[5].startswith("이 문서를 가리키던")
    assert cpb.REQUIRED_CHECKS[6].startswith("영향받는 문서의 요약")
    assert cpb.REQUIRED_CHECKS[7].startswith("필요한 테스트")
    assert cpb.REQUIRED_CHECKS[8].startswith("동작을 깨는")
