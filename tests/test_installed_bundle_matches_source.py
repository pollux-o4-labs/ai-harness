# BLUF: 전역 설치본이 동봉하는 훅·규칙이 이 소스와 바이트 동일한지 대조해, 낡은 설치본이 낡은 훅을 배포하는 조용한 실패를 소스 쪽에서 잡는다.
"""설치본 신선도 대조(소스 쪽에서 판정).

`uv tool install --force .`는 버전이 같으면 캐시된 빌드를 내주면서 종료코드 0을
낸다(실측: `docs/history/B-local-path-tool-install-serves-cached-build.md`). 그
결과 낡은 CLI가 낡은 훅을 대상 저장소에 깔고, 그 훅엔 새 검사가 없어 게이트가
조용히 아무것도 막지 않는다.

**이 대조가 훅이 아니라 테스트에 있는 이유** — 훅은 설치본에서 복사돼 나가므로
낡은 설치본엔 이 대조도 같이 없다(자기참조). 테스트는 `uv run pytest`가 소스에서
직접 돌리므로 언제나 현재 코드다. 그래서 대조는 소스 쪽에 둔다.

대조 범위는 **다른 곳으로 배포되는 산출물**(`hooks/`·`rules/`)로 좁힌다. 게이트
모듈(.py)까지 재면 편집 중 상시 빨간불이 되고, 낡은 CLI는 훅이 이미 종료코드로
잡는다. 여기 목적은 "배포물이 조용히 낡는 것"만이다.

설치본이 없으면 건너뛴다 — CI엔 전역 설치가 없고, 없다는 사실 자체는 결함이
아니다(소비 저장소는 git URL로 깔고 그 경로는 커밋 해시로 갈려 이 버그가 없다).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "ai_harness"

# 배포되는 산출물만 — 아래 폴더가 늘면 여기 등재해야 대조에 든다.
_SHIPPED_DIRS = ("hooks", "rules")


def _installed_package_dir() -> Path | None:
    """전역 `uv tool` 설치본의 `ai_harness/` 경로. 못 찾으면 None(건너뛴다).

    **PATH의 `ai-harness`를 따라가면 안 된다** — `uv run pytest`는 PATH 앞에
    프로젝트 가상환경을 두고 거기 프로젝트를 editable로 깐다. 그러면 탐지가
    소스 자신을 가리켜 대조가 항상 자기 비교가 되고, 테스트는 조용히 건너뛴
    채 "통과"한다(실측으로 이 함정을 먼저 밟았다). 그래서 전역 tool 설치
    위치를 `uv tool dir`로 직접 묻는다.
    """
    if shutil.which("uv") is None:
        return None
    try:
        out = subprocess.run(
            ["uv", "tool", "dir"], capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    # <tools>/ai-harness/lib/python3.X/site-packages/ai_harness — 파이썬 버전은
    # 머신마다 다르므로 glob으로 찾는다(설치본이 없으면 빈 결과 → 건너뛴다).
    root = Path(out.stdout.strip()) / "ai-harness" / "lib"
    found = sorted(root.glob("python*/site-packages/ai_harness"))
    for installed in found:
        # 소스를 그대로 가리키면(editable) 대조가 자기 자신이라 무의미.
        if installed.is_dir() and installed.resolve() != _SRC.resolve():
            return installed
    return None


def test_installed_bundle_matches_source() -> None:
    """설치본의 훅·규칙이 소스와 다르면 실패 — 처방은 재설치 명령이다."""
    installed = _installed_package_dir()
    if installed is None:
        pytest.skip("전역 ai-harness 설치본을 못 찾았다 — 대조 생략(CI 등).")

    stale: list[str] = []
    for sub in _SHIPPED_DIRS:
        src_dir, dst_dir = _SRC / sub, installed / sub
        if not src_dir.is_dir():
            continue
        src_files = {p.name: p for p in src_dir.iterdir() if p.is_file()}
        dst_files = {p.name: p for p in dst_dir.iterdir() if p.is_file()} if dst_dir.is_dir() else {}
        for name in sorted(set(src_files) | set(dst_files)):
            if name not in dst_files:
                stale.append(f"{sub}/{name}: 설치본에 없다")
            elif name not in src_files:
                stale.append(f"{sub}/{name}: 소스에서 지웠는데 설치본에 남았다")
            elif src_files[name].read_bytes() != dst_files[name].read_bytes():
                stale.append(f"{sub}/{name}: 내용이 다르다")

    assert not stale, (
        "전역 설치본이 소스와 어긋난다 — 이 상태로 훅을 깔면 낡은 검사가 배포된다:\n"
        + "\n".join(f"  - {s}" for s in stale)
        + "\n  → uv tool install --reinstall . && ai-harness install-hooks"
        + "\n  (--force는 버전이 같으면 캐시를 재사용하면서 종료코드 0을 낸다)"
    )


def test_detector_skips_instead_of_failing_when_uv_absent(monkeypatch) -> None:
    """uv가 없으면 실패가 아니라 건너뛰기여야 한다 — CI를 잠그면 안 된다."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert _installed_package_dir() is None


def test_detector_actually_finds_the_global_install() -> None:
    """탐지가 실제로 전역 설치본을 찾는지 — 못 찾으면 대조는 늘 건너뛰어 무의미하다.

    회귀: 처음엔 PATH의 `ai-harness`를 따라갔는데 `uv run pytest`가 프로젝트
    가상환경을 editable로 깔아 소스 자신이 잡혔고, 테스트가 조용히 건너뛰며
    통과했다. 설치본이 있는 환경에서 그 상태를 실패로 드러낸다.
    """
    tools = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True, timeout=30)
    if tools.returncode != 0:
        pytest.skip("uv tool dir 실패 — 이 환경엔 전역 설치가 없다.")
    if not (Path(tools.stdout.strip()) / "ai-harness").is_dir():
        pytest.skip("전역 ai-harness 설치본이 없다.")
    found = _installed_package_dir()
    assert found is not None, "전역 설치본이 있는데 탐지가 None을 냈다(대조가 늘 생략된다)"
    assert found.resolve() != _SRC.resolve()
