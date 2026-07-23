# BLUF: install-hooks가 대상 저장소(git 루트)의 .git/hooks로 동봉 훅을 멱등 설치하는지 검증(install_hooks.py).
"""tests/test_install_hooks.py — 훅 설치기 단위테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

import ai_harness.install_hooks as ih

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_HOOK = _REPO_ROOT / "src" / "ai_harness" / "hooks" / "pre-commit"


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)


def test_installs_pre_commit_into_target(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)  # target_root = 이 repo
    assert ih.install_hooks() == 1
    dst = repo / ".git" / "hooks" / "pre-commit"
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == _BUNDLED_HOOK.read_text(encoding="utf-8")
    assert dst.stat().st_mode & 0o111  # 실행 비트


def test_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    assert ih.install_hooks() == 1  # 첫 설치
    assert ih.install_hooks() == 0  # 이미 최신 → 재복사 0


def test_no_git_no_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # .git 없음 → 안내 후 0(크래시 아님)
    assert ih.install_hooks() == 0
