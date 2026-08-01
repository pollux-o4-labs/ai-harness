#!/usr/bin/env python3
# BLUF: check_pr_body.py의 REQUIRED_CHECKS 등 정본 상수에서 `.github/PULL_REQUEST_TEMPLATE.md`를 생성하고, `--check`로 드리프트를 감시하는 게이트(LLM 0, gen_readmes.py --check와 동형).
"""PR 템플릿 생성기 — 소스에서 생성, `--check`로 드리프트 감시.

org PR 템플릿의 `## 확인` 체크리스트를 손으로 `check_pr_body.py`의
`REQUIRED_CHECKS`와 맞춰 두면 둘이 어긋난다(드리프트) — REQUIRED_CHECKS가
바뀌었는데 템플릿을 안 고치면, 웹 UI에서 그 템플릿으로 연 PR이 체크박스 문구
불일치로 로컬 머지 게이트(`check-pr`)에서 리젝된다. 소스에서 템플릿을
생성하면 REQUIRED_CHECKS가 바뀔 때 템플릿도 같이 갱신되고, `--check`가 그
어긋남을 잡는다. 이 저장소에선 tests/test_gen_pr_template.py의 self-test가
체크인된 템플릿을 `--check`로 태워(별도 CI·훅 없이 pytest 한 번에 흡수)
드리프트를 감시한다 — gen_readmes.py `--check`와 같은 패턴.

**골격(섹션 순서·각 섹션 HTML 주석·변경유형 체크박스 라벨·하단 안내 주석)은
이 모듈이 자체 상수로 소유한다** — org 공용 템플릿에서 온 값이라 거의 안
바뀐다. **`## 확인` 섹션만 REQUIRED_CHECKS에서 렌더한다** — 계층(부모-자식
들여쓰기)은 REQUIRED_CHECKS가 flat tuple이라 못 담으므로, 항목 텍스트를
재서술하지 않고 인덱스로만 참조하는 `_CHECK_HIERARCHY`를 따로 둔다(정본은
REQUIRED_CHECKS 하나).

사용:
  ai-harness gen-pr-template                 # 생성해서 .github/PULL_REQUEST_TEMPLATE.md에 쓴다
  ai-harness gen-pr-template --check         # 드라이런: 생성물 ≠ 현재 파일이면 비영 종료
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from ai_harness.check_pr_body import CHECKLIST_SECTION, REQUIRED_CHECKS, SECTION_BUDGETS
from ai_harness.config import target_root
from ai_harness.gate_config import EXEMPT_SECTIONS

# --- 골격 상수(이 모듈 소유) --------------------------------------------------
#
# 섹션 "이름"은 재서술하지 않고 정본 상수에서 뽑는다 — SECTION_BUDGETS(예산
# 섹션 4개, 딕셔너리 순서 = 요약·변경·범위 밖·검증)와 EXEMPT_SECTIONS(변경
# 유형·관련 이슈, 이 순서로 요약과 변경 사이에 낀다). 그 사이 배치(어느 섹션
# 뒤에 어느 섹션이 오는가)는 정본 상수가 답 못 하는 골격 사실이라 이 모듈이
# 호출 순서로 소유한다.
_SUMMARY, _CHANGE, _OUT_OF_SCOPE, _VERIFICATION = SECTION_BUDGETS.keys()
# EXEMPT_SECTIONS는 대상 저장소가 오버라이드 가능한 값(config._OVERLAY_NAMES)이라,
# 개수가 2가 아니면 아래 언패킹이 불투명한 ValueError로 죽는다 — 사람이 읽을
# 메시지로 fail-loud한다(이 골격은 변경 유형·관련 이슈 2개를 가정).
if len(EXEMPT_SECTIONS) != 2:
    raise ValueError(
        "gen_pr_template는 EXEMPT_SECTIONS가 정확히 2개(변경 유형·관련 이슈)라고 "
        f"가정한다 — 현재 {len(EXEMPT_SECTIONS)}개: {EXEMPT_SECTIONS}. 골격을 이 "
        "개수에 맞게 고치거나 gate_config 오버레이를 2개로 두라."
    )
_CHANGE_TYPE, _RELATED_ISSUE = EXEMPT_SECTIONS

# 변경 유형 체크박스 라벨 — org 공용 템플릿에서 온 고정값(REQUIRED_CHECKS와
# 무관한 별도 축이라 여기서만 하드코딩).
_CHANGE_TYPE_CHECKBOXES: tuple[str, ...] = (
    "🐛 버그 수정",
    "✨ 새 기능",
    "♻️ 리팩터 (동작 변경 없음)",
    "📝 문서",
    "🔧 빌드 · 설정 · 기타",
)

# `## 확인` 체크리스트 계층 — (부모 인덱스, 자식 인덱스들) 쌍만 보유한다.
# REQUIRED_CHECKS는 flat tuple이라 계층 정보가 없으므로, 항목 텍스트를 여기
# 다시 적지 않고 인덱스로만 참조한다(정본은 REQUIRED_CHECKS 하나 — 드리프트
# 원천 차단). 계층 자체는 아래 튜플이 정본이라 말로 다시 적지 않는다.
_CHECK_HIERARCHY: tuple[tuple[int, tuple[int, ...]], ...] = (
    (0, (1, 2)),
    (3, (4, 5, 6)),
    (7, ()),
    (8, ()),
)

TEMPLATE_RELPATH = Path(".github") / "PULL_REQUEST_TEMPLATE.md"

# 종료코드 — gen_readmes.py의 DRIFT(=1) 패턴과 같은 값·같은 뜻이다: 생성물이
# 현재 상태와 다르다(파일이 아예 없는 것도 "생성물과 다름"의 한 형태로 본다).
# 이 모듈 스스로 "gen_readmes --check와 같은 패턴"이라 밝히면서 정작 `return 1`을
# 두 곳에 매직넘버로 박아 뒀던 자기일관성 문제를 여기서 바로잡는다(값은 그대로
# 1 — 동작 변경 없음).
DRIFT = 1


def _render_checklist() -> list[str]:
    """`## 확인` 체크박스 줄을 REQUIRED_CHECKS + `_CHECK_HIERARCHY`에서 렌더한다.
    자식은 `  - [ ] ...`(2칸 들여쓰기), 부모는 `- [ ] ...`."""
    lines: list[str] = []
    for parent_idx, child_idxs in _CHECK_HIERARCHY:
        lines.append(f"- [ ] {REQUIRED_CHECKS[parent_idx]}")
        for child_idx in child_idxs:
            lines.append(f"  - [ ] {REQUIRED_CHECKS[child_idx]}")
    return lines



def _write_lf(path: Path, content: str) -> None:
    """줄바꿈을 LF로 고정해 쓴다 — 생성물이 플랫폼마다 달라지면 안 된다.

    `Path.write_text`의 `newline` 인자는 3.10부터라 선언 하한(3.9)에서
    TypeError를 낸다. `open`의 같은 인자는 오래전부터 있어 그것을 쓴다.
    """
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)

def render() -> str:
    """`.github/PULL_REQUEST_TEMPLATE.md` 전체 텍스트를 생성한다."""
    lines: list[str] = []

    def h2(name: str) -> None:
        lines.append(f"## {name}")
        lines.append("")

    def comment(text: str) -> None:
        lines.append(f"<!-- {text} -->")

    def blank() -> None:
        lines.append("")

    h2(_SUMMARY)
    comment("결론 한 줄(BLUF). 리뷰어가 diff를 열기 전에 알아야 할 것 하나.")
    blank()

    h2(_CHANGE_TYPE)
    comment("해당 없으면 이 섹션째로 지워도 된다(예산 없음).")
    blank()
    lines.extend(f"- [ ] {cb}" for cb in _CHANGE_TYPE_CHECKBOXES)
    blank()

    h2(_RELATED_ISSUE)
    comment("자동 종료: Closes #123. 해당 없으면 이 섹션째로 지워도 된다(예산 없음).")
    blank()

    h2(_CHANGE)
    comment("무엇을 왜 바꿨나. 논쟁 가능한 판단은 근거까지 적는다 —")
    comment('"왜 이건 뺐나"가 리뷰에서 가장 먼저 나올 질문이면 그게 여기 들어갈 내용이다.')
    blank()

    h2(_OUT_OF_SCOPE)
    comment('이번에 안 한 것과 그게 어디로 갔는지(이슈 번호). 없으면 "없음".')
    comment('리뷰어의 "이건 왜 안 했나"를 선제 차단한다.')
    blank()

    h2(_VERIFICATION)
    comment("다른 사람이 그대로 쳐서 재현할 수 있는 명령 + 종료코드.")
    comment("무엇을 기준으로 쟀는지 밝힌다(워킹트리 아닌 커밋 산출물).")
    blank()

    h2(CHECKLIST_SECTION)
    lines.extend(_render_checklist())
    blank()
    comment("이 절은 글자 예산에 안 들어간다(문구가 고정이라 저자가 줄일 수 없다).")
    blank()

    lines.append("<!-- 이 템플릿은 조직 공용 폼(org `.github` 레포)과 게이트 폼의 통합본이다.")
    blank()
    lines.append("     어느 섹션이 필수인지, 예산이 몇 자인지, 어떤 형태만 되는지는 여기 옮겨 적지")
    lines.append("     않는다 — 옮겨 적으면 갈라진다. 정본은 ai-harness check-pr 하나이고,")
    lines.append("     위반하면 `gh pr create`·`gh pr merge`가 리젝하면서 **실측값과 함께** 무엇이")
    lines.append("     틀렸는지 알려준다. 그래서 저자는 그 스크립트를 안 읽어도 된다.")
    blank()
    lines.append("     각 섹션이 무엇을 담는지는 그 섹션 바로 위 주석에 있다.")
    lines.append("     내부 용어는 첫 등장에 괄호로 풀어야 한다 — 이 저장소를 모르는 제3자가 한 번에")
    lines.append("     읽어야 한다. -->")

    return "\n".join(lines) + "\n"


def _report_diff(current: str, generated: str, path: Path) -> None:
    """어디가 다른지 요지를 stderr에 보여준다(unified diff)."""
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        generated.splitlines(keepends=True),
        fromfile=f"{path} (현재)",
        tofile="생성물",
    )
    sys.stderr.writelines(diff)


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog=prog,
        description="PR 템플릿 생성기(check_pr_body.REQUIRED_CHECKS 등에서 파생)"
    )
    ap.add_argument("--check", action="store_true",
                    help="드라이런: 생성물과 현재 파일이 다르면 비영 종료(파일 미수정)")
    ap.add_argument("--root", default=None,
                    help="저장소 루트 경로(기본: 대상 저장소 git 루트)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else target_root()
    target = root / TEMPLATE_RELPATH
    generated = render()

    if args.check:
        if not target.is_file():
            print(
                f"[gen_pr_template] {target} 없음 — `ai-harness gen-pr-template`로 생성하라.",
                file=sys.stderr,
            )
            return DRIFT
        current = target.read_text(encoding="utf-8")
        if current != generated:
            print(
                f"[gen_pr_template] 드리프트 — {target}이 생성물과 다르다"
                f"(REQUIRED_CHECKS 등 정본이 바뀌었는데 템플릿을 안 갱신했을 수 있다).",
                file=sys.stderr,
            )
            _report_diff(current, generated, target)
            return DRIFT
        print(f"[gen_pr_template] {target} 최신.")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    _write_lf(target, generated)
    print(f"[gen_pr_template] {target} 생성/갱신.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
