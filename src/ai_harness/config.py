# BLUF: 대상 저장소가 어디이고 그 값이 무엇인지를 정하는 곳 — gate_config 오버레이(로드·우아한 실패·1회 가드)와 설치기 대상 경로 판정.
"""대상 저장소 설정 로더·오버레이, 그리고 대상 경로 판정.

설치형 CLI는 패키지에 번들된 `gate_config`(기본값)를 갖지만, 실제 판정은
**대상 저장소**의 값으로 해야 한다 — 대상 저장소 루트에 `gate_config.py`가
있으면 그 값을 번들 모듈에 얹고(오버레이), 없으면 번들 기본으로 폴백한다.

대상 루트는 `git rev-parse --show-toplevel`(현재 작업 디렉터리 기준)로 찾는다 —
훅이 `cd <repo_root>` 후 CLI를 부르므로 그 저장소가 대상이 된다.

그 루트를 아는 곳이 여기라서, 설치기들이 "어디에 깔 것인가"를 묻는 `installer_target_dir`도
여기 산다 — 오버레이와는 다른 책임이지만 같은 사실(대상 루트)에 기대므로 갈라 두면
그 사실이 두 곳에 생긴다.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import ai_harness.gate_config as _bundled

# 대상 gate_config가 덮을 수 있는 값·함수 이름 — gate_config.__all__(그 모듈이
# 스스로 밝히는 공개 표면)에서 파생한다. 손으로 이 목록을 따로 유지하면
# gate_config에 새 값을 추가하고 여기 안 넣었을 때 대상 저장소가 그 값을
# 덮어써도 조용히 무시되는 문제가 있었다(silent-wrong) — 파생이면 __all__에만
# 넣으면 자동으로 오버레이 대상이 된다. `DISABLED_GATES`는 예외: 오버레이(번들
# 모듈 속성 치환) 대상이 아니라 대상 값을 그대로 읽어 반환하는 별도 경로라
# (apply_target_config 참조) 여기서 뺀다.
_OVERLAY_NAMES = tuple(n for n in _bundled.__all__ if n != "DISABLED_GATES")
# 오버레이된 값을 `from ...gate_config import`로 굳혀 소비하는 게이트 모듈.
_CONSUMER_MODULES = (
    "ai_harness.check_pr_body",
    "ai_harness.check_doc_form",
    "ai_harness.gen_pr_template",
)


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


def installer_target_dir(
    user: bool, user_dir: Path, target_subdir: Path, tool_name: str
) -> Path | None:
    """`install_agents`·`install_rules`가 공유하는 "어디에 설치할지" 판정 가드.

    `user=True`면 `user_dir`을 그대로 쓴다. 아니면 대상 저장소 루트
    (`target_root()`) + `target_subdir` — 단 `.git`이 없으면 "git 저장소가
    아니라 설치 생략" 안내를 찍고 `None`을 반환한다(호출자는 이를 보고 0을
    반환해 종료). 두 설치기가 손으로 거의 똑같이 갖고 있던 이 가드 블록만
    뽑은 것 — **복사 정책(기존 파일을 덮을지 보존할지 등)은 서로 다르므로
    절대 합치지 않는다**, 여기선 경로 판정 하나만 공유한다.

    `install_hooks`는 이 헬퍼 대상이 아니다 — 그 설치 대상은 `.git/hooks`라
    홈 모드 자체가 없어(모든 저장소가 각자 자기 `.git`을 가진다) 골격이
    다르다. 억지로 끼워 맞추지 않는다.
    """
    if user:
        return user_dir
    root = target_root()
    if not (root / ".git").exists():
        print(f"[{tool_name}] .git 없음({root}) — git 저장소가 아니라 설치 생략"
              f"(전역 설치는 --user).")
        return None
    return root / target_subdir


def load_target_config():
    """대상 저장소 루트의 gate_config.py를 로드(없으면 번들 기본 모듈 반환).

    저장소가 자기 값(면제 섹션·끌 게이트 등)을 이 파일에 두면 그게 이긴다.
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
