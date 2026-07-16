#!/usr/bin/env python3
# BLUF: hooks/의 버전관리된 git 훅 템플릿을 .git/hooks/로 멱등 복사·chmod +x 하는 설치기(+ 옵트인 --forensics-autostart로 ~/.bashrc에 크래시 로거 자동시작 배선).
"""git 훅 설치기(stdlib only).

`.git/hooks`는 버전관리되지 않으므로, 커밋되는 `hooks/` 디렉터리의 훅 템플릿
(예: post-merge → canonical L2 auto-refresh)을 `.git/hooks/`로 복사하고 실행
비트를 켠다. 멱등 — 여러 번 돌려도 안전(같은 내용이면 재복사만). 기존 훅이 있고
내용이 다르면 덮기 전 경고를 출력한다(사용자 커스텀 훅 실수 방지).

사용:
  python scripts/install_hooks.py                      # git 훅만(기본 계약)
  python scripts/install_hooks.py --forensics-autostart # + ~/.bashrc에 크래시
                                                        #   포렌식 로거 자동시작(옵트인)

`--forensics-autostart`는 **전역 부작용**(~/.bashrc 편집)이라 기본 동작에서
제외하고 명시 옵트인으로만 배선한다 — ADR 0016의 "운영자 명시 동의 원칙"
(git 훅도 자동설치 안 함)과 동형(감사 2026-07-12).
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_SRC = REPO_ROOT / "hooks"
GIT_HOOKS_DST = REPO_ROOT / ".git" / "hooks"


def _make_executable(path: Path) -> None:
    """소유자/그룹/기타 실행 비트 추가(chmod +x 상당)."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_hooks() -> int:
    """hooks/*의 각 파일을 .git/hooks/로 복사·chmod +x. 설치 내역 출력.

    반환: 설치(복사)한 훅 개수. .git 없으면 안내 후 0 반환(크래시 아님).
    """
    if not (REPO_ROOT / ".git").exists():
        print(f"[install_hooks] .git 없음({REPO_ROOT}) — git 저장소가 아니라 설치 생략.")
        return 0
    if not HOOKS_SRC.is_dir():
        print(f"[install_hooks] hooks/ 디렉터리 없음({HOOKS_SRC}) — 설치할 훅 없음.")
        return 0

    GIT_HOOKS_DST.mkdir(parents=True, exist_ok=True)

    installed = 0
    for src in sorted(HOOKS_SRC.iterdir()):
        if not src.is_file():
            continue
        # git 훅 파일명엔 점(.)이 없다 — README.md 등 문서/보조 파일은 설치 제외.
        if "." in src.name:
            continue
        dst = GIT_HOOKS_DST / src.name
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


FORENSICS_SCRIPT = REPO_ROOT / "scripts" / "monitoring" / "crash-forensics.sh"
_FORENSICS_MARK_BEGIN = "# >>> vgo crash-forensics autostart >>>"
_FORENSICS_MARK_END = "# <<< vgo crash-forensics autostart <<<"


def _forensics_block() -> str:
    """~/.bashrc에 넣을 멱등 자동시작 블록(대화형 셸 첫 진입 시, 미실행일 때만 기동).

    WSL2는 systemd-user가 불안정해 재부팅 후 상주 기동이 마땅찮다 — bashrc-on-first
    -shell이 현실적 트리거(감사 GAP-1: 로거가 재부팅에 안 살아남던 문제). pgrep
    가드로 중복 기동 방지, nohup+disown으로 셸 종료와 절연."""
    return (
        f"{_FORENSICS_MARK_BEGIN}\n"
        f'if [ -x "{FORENSICS_SCRIPT}" ] && ! pgrep -f crash-forensics.sh >/dev/null 2>&1; then\n'
        f'  nohup "{FORENSICS_SCRIPT}" >/dev/null 2>&1 &\n'
        f"  disown 2>/dev/null || true\n"
        f"fi\n"
        f"{_FORENSICS_MARK_END}\n"
    )


def install_forensics_autostart(bashrc_path: Path | None = None) -> bool:
    """크래시 포렌식 로거를 ~/.bashrc에 멱등 자동시작 배선(감사 GAP-1).

    이미 마커 블록이 있으면 no-op(멱등). 반환: 새로 추가했으면 True. **전역 부작용
    (~/.bashrc 편집)이므로 무엇을 했는지 명시 출력**(규칙 00)."""
    bashrc = bashrc_path or (Path.home() / ".bashrc")
    existing = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
    if _FORENSICS_MARK_BEGIN in existing:
        print(f"[install_hooks] = 포렌식 자동시작 이미 배선됨({bashrc}) — 스킵(멱등).")
        return False
    block = _forensics_block()
    sep = "" if existing.endswith("\n") or not existing else "\n"
    bashrc.write_text(existing + sep + "\n" + block, encoding="utf-8")
    print(f"[install_hooks] + 포렌식 자동시작 배선 → {bashrc}\n"
          f"    (다음 대화형 셸부터 crash-forensics.sh 자동 기동 — 재부팅 생존. "
          f"해제는 {bashrc}에서 '{_FORENSICS_MARK_BEGIN}'~END 블록 삭제)")
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="git 훅 설치기 + (옵트인) 포렌식 자동시작 배선")
    ap.add_argument(
        "--forensics-autostart", action="store_true",
        help="~/.bashrc에 크래시 포렌식 로거 자동시작을 배선(전역 부작용 — 명시 옵트인). "
             "미지정 시 git 훅만 설치.",
    )
    args = ap.parse_args(argv)

    install_hooks()
    # ~/.bashrc 편집은 전역 부작용이라 기본 동작에 안 넣는다 — ADR 0016의
    # "운영자 명시 동의 원칙"(git 훅도 자동설치 안 함)과 동형으로 옵트인 게이트
    # (감사 리뷰 2026-07-12). 이 설치기의 기본 계약은 여전히 "git 훅만".
    if args.forensics_autostart:
        install_forensics_autostart()
    return 0


if __name__ == "__main__":
    sys.exit(main())
