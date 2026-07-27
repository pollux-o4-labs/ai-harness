# BLUF: ruff check가 위반 0인지 pytest로 고정 — [tool.ruff] 설정이 죽은 값이 아니라 실제 게이트가 되게(CI/훅 신설 없이 pytest 한 방에 흡수).
"""ruff 린트 self-test.

`[tool.ruff]` 설정만 있고 아무도 `ruff check`를 호출하지 않으면 죽은 설정이다 —
새 위반이 조용히 들어와도 안 걸린다. 이 파일이 `ruff check`를 pytest에 걸어, 다른
게이트들과 같은 방식(tests/의 pytest 자기검증)으로 "배선"을 완성한다. 별도 CI·훅
인프라 없이 `uv run pytest` 한 번에 흡수된다.

ruff가 없으면(consumer가 dev 의존성 미설치) skip한다 — 이 레포의 fail-open
철학(도구가 있을 때만 검사)과 같다. ruff는 dev 도구라 없는 환경엔 강제하지 않는다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ruff_check_is_clean():
    """`ruff check`가 exit 0(위반 0)인지 — 설정을 실제 게이트로 배선한다."""
    if shutil.which("ruff") is None:
        pytest.skip("ruff 미설치 — dev 도구라 없는 환경엔 강제 안 함(fail-open)")
    result = subprocess.run(
        ["ruff", "check", "."],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff 위반(exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
