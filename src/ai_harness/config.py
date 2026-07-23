# BLUF: 게이트가 쓸 "유효 설정"을 대상 저장소 루트의 gate_config.py에서 로드한다(없으면 번들 기본). 설치형 CLI가 어느 저장소에서 돌든 그 저장소 값으로 동작하게 하는 다리.
"""대상 저장소 설정 로더.

설치형 CLI는 패키지에 번들된 `gate_config`(기본값)를 갖지만, 실제 판정은
**대상 저장소**의 값으로 해야 한다 — 대상 저장소 루트에 `gate_config.py`가
있으면 그걸 로드하고, 없으면 번들 기본으로 폴백한다.

대상 루트는 `git rev-parse --show-toplevel`(현재 작업 디렉터리 기준)로 찾는다 —
훅이 `cd <repo_root>` 후 CLI를 부르므로 그 저장소가 대상이 된다.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import ai_harness.gate_config as _bundled


def target_root() -> Path:
    """대상 저장소 루트 — `git rev-parse --show-toplevel`, 실패 시 현재 디렉터리."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return Path.cwd()


def load_target_config():
    """대상 저장소 루트의 gate_config.py를 로드(없으면 번들 기본 모듈 반환).

    저장소가 자기 값(은어·면제 섹션·끌 게이트 등)을 이 파일에 두면 그게 이긴다.
    없으면 번들 기본(빈 은어 등)으로 폴백한다 — core는 어느 저장소 값도 모른다."""
    cfg_path = target_root() / "gate_config.py"
    if not cfg_path.is_file():
        return _bundled
    spec = importlib.util.spec_from_file_location("_target_gate_config", cfg_path)
    if spec is None or spec.loader is None:
        return _bundled
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def disabled_gates() -> tuple[str, ...]:
    """대상 저장소가 끈 게이트 서브커맨드 이름들(기본: 없음 = 전부 켬)."""
    return tuple(getattr(load_target_config(), "DISABLED_GATES", ()))
