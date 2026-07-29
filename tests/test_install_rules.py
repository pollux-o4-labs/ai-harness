# BLUF: install-rules가 동봉 공용 조문을 대상 .claude/rules/(또는 --user면 ~/.claude/rules/)로 복사하고, 정본이라 기존 사본을 덮는지 검증(install_rules.py).
"""tests/test_install_rules.py — 공용 규칙 설치기 단위테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

import ai_harness.install_rules as ir

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED = _REPO_ROOT / "src" / "ai_harness" / "rules"


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)


def _bundled_names() -> list[str]:
    # 폴더 인덱스 README.md는 조문이 아니라 이 패키지 안 색인이다 — 기대치도 맞춘다.
    return sorted(p.name for p in _BUNDLED.glob("*.md") if p.name != "README.md")


def test_installs_rules_into_target(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)  # target_root = 이 repo
    names = _bundled_names()
    assert ir.install_rules() == len(names)
    dst = repo / ".claude" / "rules"
    assert sorted(p.name for p in dst.glob("*.md")) == names
    assert not (dst / "README.md").exists()  # 폴더 인덱스는 조문 아님 → 미설치
    for name in names:
        assert (dst / name).read_text(encoding="utf-8") == (
            _BUNDLED / name).read_text(encoding="utf-8")


def test_overwrites_existing_copy(tmp_path, monkeypatch):
    """조문은 정본이라 덮는다 — 안 덮으면 패키지를 올려도 옛 조문이 남는다.

    `install_agents`(보존)와 정책이 반대인 지점이라 회귀로 고정한다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    dst = repo / ".claude" / "rules"
    dst.mkdir(parents=True)
    name = _bundled_names()[0]
    stale = dst / name
    stale.write_text("옛 조문\n", encoding="utf-8")
    ir.install_rules()
    assert stale.read_text(encoding="utf-8") == (_BUNDLED / name).read_text(encoding="utf-8")


def test_user_mode_installs_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() → tmp_path (POSIX)
    assert ir.install_rules(user=True) == len(_bundled_names())
    installed = tmp_path / ".claude" / "rules" / _bundled_names()[0]
    assert installed.is_file()


def test_no_git_skips(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # .git 없음 → 0 (전역 설치는 --user)
    assert ir.install_rules() == 0


def test_cli_routes_install_rules(tmp_path, monkeypatch):
    """CLI 서브커맨드로도 닿는다 — 배선이 빠지면 사용자는 못 부른다."""
    from ai_harness.cli import main as cli_main

    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    assert cli_main(["install-rules"]) == 0
    assert (repo / ".claude" / "rules" / _bundled_names()[0]).is_file()
