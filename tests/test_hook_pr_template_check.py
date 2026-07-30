# BLUF: pre-commit 훅에 배선된 gen-pr-template --check가 서식 미사용 저장소는 막지 않고, 서식이 있고 어긋난 저장소는 막는지 실제 훅(bash)을 실행해 검증.
"""tests/test_hook_pr_template_check.py — pre-commit 훅의 PR 템플릿 드리프트 배선 회귀.

훅은 bash라 pytest가 함수로 직접 부를 수 없다 — 실제 임시 git 저장소에서
`bash .../hooks/pre-commit`을 서브프로세스로 태워 두 성질을 검증한다:

  1. 서식 파일(`.github/PULL_REQUEST_TEMPLATE.md`)이 **없는** 저장소 →
     훅이 그 검사 때문에 막지 않는다(이 기능을 안 쓰는 저장소는 존중한다).
  2. 서식 파일이 **있고 정본 생성물과 어긋난** 저장소 → 훅이 막는다(비영 종료).

DB도 LLM(언어모델)도 안 쓴다 — git·설치된 ai-harness CLI만 서브프로세스로 부른다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / "src" / "ai_harness" / "hooks" / "pre-commit"

# 설치된 콘솔 스크립트(`ai-harness`)가 사는 venv bin — test_config.py·
# test_check_pr_body.py와 같은 관용구(sys.executable의 형제 bin/에 콘솔
# 스크립트가 같이 깔린다). 전역 PATH에 낡은 별도 설치본이 있어도 이걸 앞에
# 얹어 "이 저장소의 현재 코드"가 우선하게 한다.
_VENV_BIN = str(Path(sys.executable).parent)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   check=True, capture_output=True)


def _env() -> dict:
    return {**os.environ, "PATH": f"{_VENV_BIN}:{os.environ.get('PATH', '')}"}


def _run_ai_harness(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ai-harness", *args], cwd=str(repo), env=_env(),
                          capture_output=True, text=True)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(_HOOK)], cwd=str(repo), env=_env(),
                          capture_output=True, text=True)


def _make_readme_gate_clean(repo: Path) -> None:
    """gen-readmes --check가 통과하도록 README 인덱스를 미리 최신화한다 — 무관한
    게이트(README 인덱스 어긋남)가 걸려 PR 템플릿 검사 결과를 가리지 않게 격리."""
    r = _run_ai_harness(repo, "gen-readmes")
    assert r.returncode == 0, f"테스트 준비 실패(gen-readmes): {r.stdout}{r.stderr}"


def test_hook_does_not_block_when_template_file_absent(tmp_path):
    """서식 파일을 아예 안 만든 저장소 — PR 템플릿 검사가 막을 이유가 없다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_readme_gate_clean(repo)

    assert not (repo / ".github" / "PULL_REQUEST_TEMPLATE.md").exists()

    result = _run_hook(repo)
    assert result.returncode == 0, (
        f"서식 미사용 저장소인데 훅이 막았다 — stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_hook_blocks_when_template_file_diverges(tmp_path):
    """서식 파일이 있고 정본 생성물과 어긋나면 훅이 막는다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_readme_gate_clean(repo)

    gen = _run_ai_harness(repo, "gen-pr-template")
    assert gen.returncode == 0, f"테스트 준비 실패(gen-pr-template): {gen.stdout}{gen.stderr}"
    template = repo / ".github" / "PULL_REQUEST_TEMPLATE.md"
    template.write_text(
        template.read_text(encoding="utf-8").replace("가독성", "손으로바꾼텍스트"),
        encoding="utf-8",
    )

    result = _run_hook(repo)
    assert result.returncode != 0, (
        f"서식이 어긋났는데 훅이 통과시켰다 — stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # 실패 원인이 실제로 PR 템플릿 드리프트인지 확인 — 다른 게이트가 우연히
    # 걸려 통과한 오탐(false positive)이 아님을 메시지로 못박는다.
    assert "드리프트" in result.stderr and "PULL_REQUEST_TEMPLATE" in result.stderr, (
        f"실패했지만 원인이 PR 템플릿 드리프트가 아닐 수 있다 — stderr={result.stderr!r}"
    )


# --- 경로 리터럴이 생성기 상수와 같은가 ---------------------------------------
#
# 훅은 이 경로를 CLI에 물어보지 않고 직접 쓴다 — 물어보게 하면 훅이 "새 CLI에만
# 있는 물음"에 기대게 되고 설치본이 낡은 순간 훅이 죽는다(실측으로 겪었다).
# 대신 두 곳이 갈라지는 것은 여기서 빌드타임에 막는다.


def test_hook_template_path_matches_generator_constant():
    """훅이 쓰는 경로 리터럴이 생성기의 정본 상수와 같다."""
    import ai_harness.gen_pr_template as gpt

    hook_text = _HOOK.read_text(encoding="utf-8")
    assert gpt.TEMPLATE_RELPATH.as_posix() in hook_text, (
        f"훅의 경로 리터럴이 {gpt.TEMPLATE_RELPATH.as_posix()} 와 갈라졌다"
    )


# --- 낡은 설치본을 조용히 넘기지 않는다 ---------------------------------------
#
# 조용히 건너뛰면 "검사가 도는 줄 알았는데 안 돌던" 사고가 된다 — 조용한 통과와
# 조용한 부재는 겉모습이 같다. 이 도구를 안 쓰는 저장소(CLI 자체가 없음)와
# 쓰기로 해놓고 갱신을 안 한 상태(CLI가 낡음)는 다르게 다뤄야 한다.


def test_hook_fails_loudly_when_installed_cli_is_too_old(tmp_path):
    """서브커맨드를 모르는 낡은 CLI에서는 훅이 조용히 통과하지 않는다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_readme_gate_clean(repo)
    _run_ai_harness(repo, "gen-pr-template")  # 서식을 만들어 검사 대상이 되게

    # `gen-pr-template`를 모르는 옛 CLI 흉내 — 그 서브커맨드만 실패시킨다.
    shim_dir = tmp_path / "oldbin"
    shim_dir.mkdir()
    shim = shim_dir / "ai-harness"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "gen-pr-template" ]; then\n'
        '  echo "[ai-harness] 알 수 없는 명령: gen-pr-template" >&2\n'
        "  exit 2\n"
        "fi\n"
        f'exec {_VENV_BIN}/ai-harness "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)

    env = dict(os.environ, PATH=f"{shim_dir}{os.pathsep}{_VENV_BIN}{os.pathsep}{os.environ['PATH']}")
    proc = subprocess.run(["bash", str(_HOOK)], cwd=str(repo), env=env,
                          capture_output=True, text=True)

    assert proc.returncode != 0, "낡은 설치본인데 훅이 조용히 통과했다"
    assert "gen-pr-template" in proc.stderr, f"무엇이 문제인지 안 알렸다: {proc.stderr!r}"
