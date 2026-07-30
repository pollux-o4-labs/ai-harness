# BLUF: 대상 저장소 gate_config 로드·값 오버레이·프로세스당-1회 가드·우아한 실패를 검증(config.py).
"""tests/test_config.py — 대상 저장소 설정 로더·오버레이 단위테스트.

값 오버레이의 '성공 경로'는 프로세스당-1회 가드 때문에 in-process로 못 태운다
(게이트 모듈이 테스트 수집 시 이미 import됨) — 실제 경로는 설치형 CLI를
서브프로세스로 띄워 검증하고, 로드·가드·우아한 실패는 in-process로 검증한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import ai_harness.config as config
import ai_harness.gate_config as gate_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_BIN = str(Path(sys.executable).parent)

_GOOD_BODY = """\
## 요약

PR 본문에 게이트를 건다.

## 변경 유형

- [x] ✨ 새 기능

## 관련 이슈

Closes #1

## 변경

- 한 줄 변경.

## 범위 밖

없음.

## 검증

`uv run pytest` → exit 0.

## 확인

- [x] 가독성을 높이는 검수를 진행했다 (PR body 및 comment 대상)
  - [x] 과한 내부 은어 사용 검수했다
  - [x] 비전문가, 제3자도 쉽게 이해할 수 있도록 작성되었는지 검토했다
- [x] 이 변경이 다른 문서를 낡게 하지 않았는지, 작업 중 발견한 기존 stale은 고쳤는지 검토했다 (PR이 영향을 주는 문서들)
  - [x] 바꾼 값·사실을 옮겨 적은 다른 문서도 같이 고쳤는지 확인했다
  - [x] 이 문서를 가리키던 링크·참조가 끊기지 않았는지 확인했다
  - [x] 영향받는 문서의 요약(맨 위 한 줄)이 여전히 맞는지 확인했다
- [x] 필요한 테스트를 추가하거나 갱신했다
- [x] 동작을 깨는 변경(breaking change)이라면 본문에 명시했다
"""


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)


# --- _OVERLAY_NAMES 파생(gate_config.__all__과의 손동기화 방지) -----------------
def test_overlay_names_derived_from_gate_config_public_surface():
    """_OVERLAY_NAMES는 gate_config.__all__(DISABLED_GATES 제외)에서 파생된다 —
    두 목록을 손으로 따로 유지하다 어긋나는 회귀를 막는다. gate_config에 새
    공개 값을 추가하고 __all__에 넣으면(그 모듈 자신의 공개 표면 선언) 이
    목록도 자동으로 따라온다."""
    assert set(config._OVERLAY_NAMES) == set(gate_config.__all__) - {"DISABLED_GATES"}
    assert "DISABLED_GATES" not in config._OVERLAY_NAMES


# --- target_root ---------------------------------------------------------------
def test_target_root_is_git_toplevel(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert config.target_root() == repo.resolve()


def test_target_root_falls_back_to_cwd_outside_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # /tmp/... 는 git repo 아님 → cwd 폴백
    assert config.target_root() == Path.cwd()


# --- load_target_config --------------------------------------------------------
def test_load_returns_bundled_when_no_config(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert config.load_target_config() is gate_config


def test_load_reads_target_config(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    (tmp_path / "gate_config.py").write_text('EXEMPT_SECTIONS = ("부록",)\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod = config.load_target_config()
    assert mod is not gate_config
    assert mod.EXEMPT_SECTIONS == ("부록",)


def test_load_malformed_config_exits_with_message_not_traceback(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    (tmp_path / "gate_config.py").write_text("EXEMPT_SECTIONS = (  # 닫는 괄호 없음\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        config.load_target_config()
    assert "대상 설정 로드 실패" in str(ei.value)


# --- apply_target_config: 프로세스당-1회 가드 -----------------------------------
def test_apply_bundled_returns_disabled_gates(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)  # 대상 config 없음 → 번들, 가드 미적용
    assert config.apply_target_config() == ()


def test_apply_guard_fires_when_consumer_already_imported(tmp_path, monkeypatch):
    import ai_harness.check_pr_body  # noqa: F401  (sys.modules에 확실히 올림)
    _init_repo(tmp_path)
    (tmp_path / "gate_config.py").write_text('EXEMPT_SECTIONS = ("부록",)\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="프로세스당 1회"):
        config.apply_target_config()


# --- 값 오버레이 실제 경로: 서브프로세스(프로세스당-1회 전제 충족) ---------------
def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{_VENV_BIN}:{os.environ.get('PATH', '')}"}
    return subprocess.run(["ai-harness", *args], cwd=str(repo), env=env,
                          capture_output=True, text=True)


def test_overlay_applies_target_value_via_subprocess(tmp_path):
    """대상 저장소 값이 실제로 얹히는지 — 허용 섹션 목록으로 양방향 확인한다.

    예시를 은어 목록에서 면제 섹션으로 갈았다. 은어 게이트는 걷어냈기 때문이며
    (어휘는 목록으로 쫓을 수 없어 리뷰어 몫), 검증하려는 것은 오버레이 경로
    자체이지 어느 값인지가 아니다. 한쪽만 보면 "원래 통과였다"와 구분이 안
    되므로, core에서 리젝되는 본문이 대상 값에서 통과하는 것을 같이 본다.
    """
    with_extra = _GOOD_BODY.replace(
        "## 확인", "## 부록\n\n- [x] 덧붙일 것.\n\n## 확인")

    core = tmp_path / "core"
    _init_repo(core)
    body = core / "body.md"
    body.write_text(with_extra, encoding="utf-8")
    r_core = _run_cli(core, "check-pr", "--body-file", str(body))
    assert r_core.returncode != 0, "core 기본값엔 '부록'이 없어 미지 섹션 리젝이어야 한다"
    assert "부록" in r_core.stdout + r_core.stderr

    target = tmp_path / "target"
    _init_repo(target)
    (target / "gate_config.py").write_text(
        'EXEMPT_SECTIONS = ("변경 유형", "관련 이슈", "부록")\n', encoding="utf-8")
    body2 = target / "body.md"
    body2.write_text(with_extra, encoding="utf-8")
    r_target = _run_cli(target, "check-pr", "--body-file", str(body2))
    assert r_target.returncode == 0, r_target.stdout + r_target.stderr


def test_disabled_gate_is_noop_via_subprocess(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "README.txt").write_text("hi\n", encoding="utf-8")
    assert _run_cli(repo, "gen-readmes", "--check").returncode != 0  # 기본: 요구로 비영
    (repo / "gate_config.py").write_text('DISABLED_GATES = ("gen-readmes",)\n', encoding="utf-8")
    assert _run_cli(repo, "gen-readmes", "--check").returncode == 0  # 끄면 no-op


def test_malformed_config_no_raw_traceback_via_subprocess(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "gate_config.py").write_text("EXEMPT_SECTIONS = (  # 오타\n", encoding="utf-8")
    body = repo / "b.md"
    body.write_text("x\n", encoding="utf-8")
    r = _run_cli(repo, "check-pr", "--body-file", str(body))
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "대상 설정 로드 실패" in out
    assert "Traceback" not in out
