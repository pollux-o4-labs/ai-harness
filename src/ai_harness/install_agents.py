#!/usr/bin/env python3
# BLUF: 패키지에 동봉된 리뷰어 에이전트 템플릿을 대상 저장소의 .claude/agents/(또는 --user면 ~/.claude/agents/)로 복사하는 설치기 — 기존 파일은 안 덮어 저장소 커스터마이즈를 보존한다.
"""리뷰어 에이전트 설치기(stdlib only).

패키지에 동봉된 `agents/` 템플릿(.md)을 대상 저장소의 `.claude/agents/`로
복사한다. 템플릿엔 `{...}` 플레이스홀더가 있어 — 설치 후 저장소가 자기 규약
경로·근거 정본을 채운다(설치는 복사까지, 커스터마이즈는 저장소 몫).

`install_hooks`와 달리 **기존 파일은 덮지 않는다** — 훅은 관리되는 정본이라
갱신 복사하지만, 에이전트는 설치 후 저장소가 손대는 템플릿이라 덮으면
그 커스터마이즈를 잃는다. 이미 있으면 건너뛴다(멱등).

  ai-harness install-agents          # 대상 저장소 .claude/agents/ 로
  ai-harness install-agents --user   # ~/.claude/agents/ (모든 저장소 공용)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# 에이전트 템플릿은 패키지에 동봉된다(설치본과 함께 이동).
_AGENTS_SRC = Path(__file__).resolve().parent / "agents"


def install_agents(user: bool = False) -> int:
    """동봉 agents/*.md를 대상의 .claude/agents/로 복사(기존은 보존). 설치 개수 반환.

    user=True면 ~/.claude/agents/(모든 저장소 공용), 아니면 대상 저장소(git 루트).
    """
    if user:
        dst_dir = Path.home() / ".claude" / "agents"
    else:
        from ai_harness.config import target_root

        root = target_root()
        if not (root / ".git").exists():
            print(f"[install_agents] .git 없음({root}) — git 저장소가 아니라 설치 생략"
                  f"(전역 설치는 --user).")
            return 0
        dst_dir = root / ".claude" / "agents"

    if not _AGENTS_SRC.is_dir():
        print(f"[install_agents] 동봉 에이전트 템플릿 없음({_AGENTS_SRC}) — 설치할 것 없음.")
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)

    installed = 0
    for src in sorted(_AGENTS_SRC.glob("*.md")):
        if src.name == "README.md":
            continue  # 폴더 개요 README는 에이전트가 아니라 설치 제외
        dst = dst_dir / src.name
        if dst.exists():
            print(f"[install_agents] = {src.name} (이미 있음 — 덮지 않음, 커스터마이즈 보존)")
            continue
        shutil.copy2(src, dst)
        installed += 1
        print(f"[install_agents] + {src.name} → {dst}")

    print(f"[install_agents] 완료 — {installed}개 설치(신규만). "
          f"템플릿의 {{...}} 플레이스홀더를 이 저장소 값으로 채워라.")
    return installed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="리뷰어 에이전트 템플릿 설치기")
    ap.add_argument(
        "--user", action="store_true",
        help="~/.claude/agents/(모든 저장소 공용)에 설치. 미지정 시 대상 저장소 .claude/agents/.",
    )
    args = ap.parse_args(argv)
    install_agents(user=args.user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
