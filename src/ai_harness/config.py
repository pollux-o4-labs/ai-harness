# BLUF: 대상 저장소 루트의 gate_config.py 값을 번들 모듈에 얹어(오버레이) 설치형 CLI가 그 저장소 값으로 동작하게 하는 다리 — 로드·우아한 실패·프로세스당-1회 가드.
"""대상 저장소 설정 로더·오버레이.

설치형 CLI는 패키지에 번들된 `gate_config`(기본값)를 갖지만, 실제 판정은
**대상 저장소**의 값으로 해야 한다 — 대상 저장소 루트에 `gate_config.py`가
있으면 그 값을 번들 모듈에 얹고(오버레이), 없으면 번들 기본으로 폴백한다.

대상 루트는 `git rev-parse --show-toplevel`(현재 작업 디렉터리 기준)로 찾는다 —
훅이 `cd <repo_root>` 후 CLI를 부르므로 그 저장소가 대상이 된다.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import ai_harness.gate_config as _bundled

# 대상 gate_config가 덮을 수 있는 값·함수 이름(정의 안 한 건 번들 기본 상속).
_OVERLAY_NAMES = (
    "JARGON_TERMS", "EXEMPT_SECTIONS", "EXTRA_AUTOGEN_MARKERS",
    "RULE_DOC_AUTHORING", "RULE_REVIEW_EVIDENCE", "build_exempt_shape", "rule_cite",
)
# 오버레이된 값을 `from ...gate_config import`로 굳혀 소비하는 게이트 모듈.
_CONSUMER_MODULES = ("ai_harness.check_pr_body", "ai_harness.check_doc_form")


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
    설정 파일에 오류가 있으면 raw traceback 대신 사람이 읽을 메시지로 종료한다 —
    저장소 설정 하나의 오타가 게이트 전부를 알 수 없는 에러로 깨는 걸 막는다.
    """
    cfg_path = target_root() / "gate_config.py"
    if not cfg_path.is_file():
        return _bundled
    spec = importlib.util.spec_from_file_location("_target_gate_config", cfg_path)
    if spec is None or spec.loader is None:
        return _bundled
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        raise SystemExit(
            f"[ai-harness] 대상 설정 로드 실패: {cfg_path}\n  {type(e).__name__}: {e}"
        )
    return mod


def apply_target_config() -> tuple[str, ...]:
    """대상 gate_config 값을 번들 모듈에 오버레이하고 `DISABLED_GATES`를 반환한다.

    CLI는 매 호출이 새 프로세스라, 게이트 모듈이 `from ...gate_config import`로
    값을 굳히기 **전에** 번들 모듈 속성을 대상 값으로 덮는다(그 뒤 지연 import가
    덮인 값을 읽는다). 게이트 모듈이 **이미 로드된 뒤**면 오버레이가 그 굳은
    이름에 안 닿아 조용히 stale해진다 — 그 전제(프로세스당 1회) 위반을 fail-loud로
    막는다(같은 프로세스 재호출·배치 러너 미지원, silent-wrong 방지).
    """
    target = load_target_config()
    if target is _bundled:
        return tuple(getattr(_bundled, "DISABLED_GATES", ()))
    already = [m for m in _CONSUMER_MODULES if m in sys.modules]
    if already:
        raise RuntimeError(
            f"[ai-harness] 대상 gate_config 오버레이 실패 — 게이트 모듈이 이미 "
            f"로드됨({', '.join(already)}). CLI는 프로세스당 1회 호출만 지원한다."
        )
    for name in _OVERLAY_NAMES:
        if hasattr(target, name):
            setattr(_bundled, name, getattr(target, name))
    return tuple(getattr(target, "DISABLED_GATES", ()))
