# BLUF: install-agents가 동봉 리뷰어 템플릿을 대상 .claude/agents/(또는 --user면 ~/.claude/agents/)로 복사하고 기존 커스터마이즈는 보존하는지 검증(install_agents.py).
"""tests/test_install_agents.py — 에이전트 설치기 단위테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

import ai_harness.install_agents as ia

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED = _REPO_ROOT / "src" / "ai_harness" / "agents"


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)


def _bundled_names() -> list[str]:
    return sorted(p.name for p in _BUNDLED.glob("*.md"))


def test_installs_templates_into_target(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)  # target_root = 이 repo
    names = _bundled_names()
    assert ia.install_agents() == len(names)
    dst = repo / ".claude" / "agents"
    assert sorted(p.name for p in dst.glob("*.md")) == names
    for name in names:  # 신규 복사 = 내용 동일
        assert (dst / name).read_text(encoding="utf-8") == (_BUNDLED / name).read_text(encoding="utf-8")


def test_preserves_existing_customization(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    dst = repo / ".claude" / "agents"
    dst.mkdir(parents=True)
    custom = dst / "reviewer-code.md"
    custom.write_text("커스텀 내용\n", encoding="utf-8")  # 저장소가 이미 손댐
    ia.install_agents()
    assert custom.read_text(encoding="utf-8") == "커스텀 내용\n"  # 안 덮음(보존)


def test_user_mode_installs_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() → tmp_path (POSIX)
    assert ia.install_agents(user=True) == len(_bundled_names())
    assert (tmp_path / ".claude" / "agents" / "reviewer-code.md").is_file()


def test_no_git_skips(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # .git 없음 → 0 (전역 설치는 --user)
    assert ia.install_agents() == 0
