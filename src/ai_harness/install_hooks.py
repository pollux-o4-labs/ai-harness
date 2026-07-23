#!/usr/bin/env python3
# BLUF: 패키지에 동봉된 git 훅 템플릿을 대상 저장소(git rev-parse)의 .git/hooks/로 멱등 복사·chmod +x 하는 설치기.
"""git 훅 설치기(stdlib only).

`.git/hooks`는 버전관리되지 않으므로, 패키지에 동봉된 `hooks/` 훅 템플릿을
**대상 저장소**의 `.git/hooks/`로 복사하고 실행 비트를 켠다. 멱등 — 여러 번
돌려도 안전(같은 내용이면 재복사만). 기존 훅이 있고 내용이 다르면 덮기 전
경고를 출력한다(사용자 커스텀 훅 실수 방지).

대상 저장소는 현재 작업 디렉터리의 git 루트(`git rev-parse --show-toplevel`)다.

사용:
  ai-harness install-hooks
"""
from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

# 훅 템플릿은 패키지에 동봉된다(설치본과 함께 이동) — 여기서 대상 저장소로 복사.
_HOOKS_SRC = Path(__file__).resolve().parent / "hooks"


def _make_executable(path: Path) -> None:
    """소유자/그룹/기타 실행 비트 추가(chmod +x 상당)."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_hooks() -> int:
    """동봉 hooks/*를 대상 저장소의 .git/hooks/로 복사·chmod +x. 설치 내역 출력.

    대상 저장소는 현재 디렉터리의 git 루트다. 반환: 설치(복사)한 훅 개수.
    .git 없으면 안내 후 0 반환(크래시 아님).
    """
    from ai_harness.config import target_root

    root = target_root()
    git_hooks_dst = root / ".git" / "hooks"
    if not (root / ".git").exists():
        print(f"[install_hooks] .git 없음({root}) — git 저장소가 아니라 설치 생략.")
        return 0
    if not _HOOKS_SRC.is_dir():
        print(f"[install_hooks] 동봉 훅 템플릿 없음({_HOOKS_SRC}) — 설치할 훅 없음.")
        return 0

    git_hooks_dst.mkdir(parents=True, exist_ok=True)

    installed = 0
    for src in sorted(_HOOKS_SRC.iterdir()):
        if not src.is_file():
            continue
        # git 훅 파일명엔 점(.)이 없다 — README.md 등 문서/보조 파일은 설치 제외.
        if "." in src.name:
            continue
        dst = git_hooks_dst / src.name
        src_text = src.read_text(encoding="utf-8")
        if dst.exists():
            dst_text = dst.read_text(encoding="utf-8", errors="replace")
            if dst_text == src_text:
                _make_executable(dst)  # 내용 동일 — 실행비트만 보장(멱등)
                print(f"[install_hooks] = {src.name} (이미 최신, 실행비트 확인)")
                continue
            print(f"[install_hooks] ⚠ 기존 {src.name}가 다름 — 덮어씀"
                  f"(백업: {dst.name}.bak)")
            shutil.copy2(dst, dst.with_suffix(dst.suffix + ".bak"))
        shutil.copy2(src, dst)
        _make_executable(dst)
        installed += 1
        print(f"[install_hooks] + {src.name} → {dst}")

    print(f"[install_hooks] 완료 — {installed}개 설치/갱신.")
    return installed


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="git 훅 설치기")
    ap.parse_args(argv)

    install_hooks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
