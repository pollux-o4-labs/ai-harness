#!/usr/bin/env python3
# BLUF: 패키지에 동봉된 공용 규칙 조문을 대상 저장소의 .claude/rules/(또는 --user면 ~/.claude/rules/)로 복사하는 설치기 — 조문은 정본이라 기존 파일을 덮는다.
"""공용 규칙 설치기(stdlib only).

여러 저장소가 함께 쓰는 규칙(예: GitHub 이슈 연결 관례)은 저장소 취향이 아니라
플랫폼 사실에 가깝다. 그런 조문의 정본은 이 패키지가 소유하고, 각 저장소는
`.claude/rules/`에 놓인 사본을 읽는다.

`install_agents`와 달리 **기존 파일을 덮는다**. 에이전트 템플릿은 설치 후
저장소가 자기 값으로 채우는 것이라 덮으면 그 손질을 잃지만, 공용 조문은
저장소가 고칠 대상이 아니다 — 안 덮으면 패키지를 올려도 옛 조문이 남아
조용히 낡는다.

다만 덮어쓰기가 지우는 것은 **다시 설치할 때의** 낡음뿐이다. 재설치를 안 하면
사본은 그대로 낡고, 그걸 알려줄 신호는 없다(드리프트 감시는 실제 소비 저장소가
생긴 뒤에 만들 일이라 여기 없다).

저장소가 이 폴더를 읽게 하는 배선(AGENTS.md 한 줄)은 자동화하지 않는다 —
저장소마다 문서 구조가 달라 마커 splice가 필요한데, 그건 실제 소비 저장소가
생긴 뒤에 만들 일이다.

  ai-harness install-rules          # 대상 저장소 .claude/rules/ 로
  ai-harness install-rules --user   # ~/.claude/rules/ (그 머신의 모든 저장소)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# 조문은 패키지에 동봉된다(설치본과 함께 이동).
_RULES_SRC = Path(__file__).resolve().parent / "rules"

# 대상에서 조문이 놓이는 곳. `.claude/agents/`와 같은 자리에 둔다 — 에이전트가
# 읽는 것들이 한 곳에 모여야 저장소가 가리킬 경로가 하나로 준다.
_DST_RELDIR = Path(".claude") / "rules"


def install_rules(user: bool = False) -> int:
    """동봉 rules/*.md를 대상의 .claude/rules/로 복사(덮어쓰기). 설치 개수 반환.

    user=True면 ~/.claude/rules/(그 머신의 모든 저장소), 아니면 대상 저장소.
    """
    from ai_harness.config import installer_target_dir

    dst_dir = installer_target_dir(
        user, Path.home() / _DST_RELDIR, _DST_RELDIR, "install_rules"
    )
    if dst_dir is None:
        return 0

    if not _RULES_SRC.is_dir():
        print(f"[install_rules] 동봉 공용 규칙 없음({_RULES_SRC}) — 설치할 것 없음.")
        return 0

    # 폴더 개요 README는 조문이 아니라 이 패키지 안에서만 쓰는 색인이라 제외한다.
    rules = [p for p in sorted(_RULES_SRC.glob("*.md")) if p.name != "README.md"]
    if not rules:
        print(f"[install_rules] 동봉 조문 0건({_RULES_SRC}) — 설치할 것 없음.")
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in rules:
        dst = dst_dir / src.name
        shutil.copy2(src, dst)
        print(f"[install_rules] + {src.name} → {dst}")

    print(f"[install_rules] 완료 — {len(rules)}개 설치(덮어쓰기). "
          f"저장소 AGENTS.md에 이 폴더를 가리키는 줄을 두어라.")
    return len(rules)


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog=prog, description="공용 규칙 조문 설치기")
    ap.add_argument(
        "--user", action="store_true",
        help="~/.claude/rules/(그 머신의 모든 저장소)에 설치. 미지정 시 대상 저장소.",
    )
    args = ap.parse_args(argv)
    install_rules(user=args.user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
