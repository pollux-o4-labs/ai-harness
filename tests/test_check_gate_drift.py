# BLUF: check_gate_drift의 core 바이트 비교·특정 저장소 지시 검사·형제 경로 부재 시 skip을 검증.
"""tests/test_check_gate_drift.py — 게이트 core 드리프트 검사 단위테스트.

DB도 LLM(언어모델)도 안 쓴다 — 순수 파일 비교라 어디서 돌려도 같은 결과다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_gate_drift as cgd  # noqa: E402


# --- check_self_reference ----------------------------------------------------

def test_self_reference_detects_pattern(tmp_path):
    p = tmp_path / "check_pr_body.py"
    p.write_text("# 이 저장소는 특별하다\nprint(1)\n", encoding="utf-8")
    violations = cgd.check_self_reference(p)
    assert any("특정 저장소 지시 표현" in v for v in violations)


@pytest.mark.parametrize("phrase", ["이 저장소", "우리 레포", "이 레포"])
def test_self_reference_detects_all_variants(tmp_path, phrase):
    p = tmp_path / "check_pr_body.py"
    p.write_text(f"# {phrase}엔 docs/rules가 없다\n", encoding="utf-8")
    assert cgd.check_self_reference(p) != []


def test_self_reference_passes_clean_file(tmp_path):
    p = tmp_path / "check_pr_body.py"
    p.write_text("# 특정 저장소를 가리키지 않는 일반 서술\nprint(1)\n", encoding="utf-8")
    assert cgd.check_self_reference(p) == []


def test_real_core_files_have_no_self_reference():
    """합성 픽스처가 아니라 실제 `_REPO_ROOT`의 core 파일 자체를 스캔한다 —
    함수가 옳아도 실 파일에 표현이 남아 있으면 이 파일이 그 누출을 잡아야
    한다(안티-hollow-green: check_self_reference를 tmp_path로만 검증하면
    "함수는 맞는데 실제로 안 돌려봄"이 통과할 수 있다)."""
    violations: list[str] = []
    for rel in cgd._SELF_REFERENCE_TARGETS:
        path = _REPO_ROOT / rel
        assert path.is_file(), f"{rel} 없음 — CORE_FILES/타깃 목록이 실제와 어긋남"
        violations.extend(cgd.check_self_reference(path))
    assert violations == [], violations


def test_self_reference_reports_line_number(tmp_path):
    p = tmp_path / "check_pr_body.py"
    p.write_text("line1\nline2\n# 이 저장소 특화\nline4\n", encoding="utf-8")
    violations = cgd.check_self_reference(p)
    assert any(f"{p}:3:" in v for v in violations)


# --- check_byte_identical ----------------------------------------------------

def _write_core_files(root: Path, content: str = "print('core')\n") -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for rel in cgd.CORE_FILES:
        (root / rel).write_text(content, encoding="utf-8")


def test_byte_identical_passes_when_same(tmp_path):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    _write_core_files(mine)
    _write_core_files(theirs)
    monkey_root = mine
    orig = cgd._REPO_ROOT
    try:
        cgd._REPO_ROOT = monkey_root  # type: ignore[attr-defined]
        assert cgd.check_byte_identical(theirs) == []
    finally:
        cgd._REPO_ROOT = orig  # type: ignore[attr-defined]


def test_byte_identical_flags_content_difference(tmp_path):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    _write_core_files(mine, content="print('mine')\n")
    _write_core_files(theirs, content="print('theirs')\n")
    orig = cgd._REPO_ROOT
    try:
        cgd._REPO_ROOT = mine  # type: ignore[attr-defined]
        violations = cgd.check_byte_identical(theirs)
        assert len(violations) == len(cgd.CORE_FILES)
        assert all("바이트가 다르다" in v for v in violations)
    finally:
        cgd._REPO_ROOT = orig  # type: ignore[attr-defined]


def test_byte_identical_flags_missing_on_canonical_side(tmp_path):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    _write_core_files(mine)
    (theirs / "scripts").mkdir(parents=True)
    # theirs엔 check_gate_drift.py만 없다(예: 형제가 아직 이 도구를 안 들여온 경우).
    for rel in cgd.CORE_FILES:
        if rel.endswith("check_gate_drift.py"):
            continue
        (theirs / rel).write_text("print('core')\n", encoding="utf-8")
    orig = cgd._REPO_ROOT
    try:
        cgd._REPO_ROOT = mine  # type: ignore[attr-defined]
        violations = cgd.check_byte_identical(theirs)
        assert any("check_gate_drift.py" in v and "없음" in v for v in violations)
    finally:
        cgd._REPO_ROOT = orig  # type: ignore[attr-defined]


def test_byte_identical_flags_missing_on_local_side(tmp_path):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    (mine / "scripts").mkdir(parents=True)
    _write_core_files(theirs)
    orig = cgd._REPO_ROOT
    try:
        cgd._REPO_ROOT = mine  # type: ignore[attr-defined]
        violations = cgd.check_byte_identical(theirs)
        assert len(violations) == len(cgd.CORE_FILES)
        assert all("파일이 없음" in v for v in violations)
    finally:
        cgd._REPO_ROOT = orig  # type: ignore[attr-defined]


def test_gate_config_excluded_from_byte_comparison():
    """gate_config.py는 저장소마다 다르라고 만든 파일이라 CORE_FILES에 없다."""
    assert "scripts/gate_config.py" not in cgd.CORE_FILES


# --- main() 통합 ------------------------------------------------------------

def test_main_skips_byte_comparison_without_env(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GATE_CANONICAL_DIR", raising=False)
    _write_core_files(tmp_path)
    monkeypatch.setattr(cgd, "_REPO_ROOT", tmp_path)
    assert cgd.main() == 0
    assert "skip" in capsys.readouterr().err


def test_main_passes_with_identical_sibling(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    _write_core_files(mine)
    _write_core_files(theirs)
    monkeypatch.setattr(cgd, "_REPO_ROOT", mine)
    monkeypatch.setenv("GATE_CANONICAL_DIR", str(theirs))
    assert cgd.main() == 0


def test_main_fails_with_differing_sibling(tmp_path, monkeypatch, capsys):
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    _write_core_files(mine, content="print('mine')\n")
    _write_core_files(theirs, content="print('theirs')\n")
    monkeypatch.setattr(cgd, "_REPO_ROOT", mine)
    monkeypatch.setenv("GATE_CANONICAL_DIR", str(theirs))
    assert cgd.main() == 1
    assert "드리프트" in capsys.readouterr().err


def test_main_fails_on_self_reference_even_without_env(tmp_path, monkeypatch):
    """형제 경로가 없어도 특정 저장소 지시 표현은 잡혀야 한다(바이트 비교와 별개 축)."""
    monkeypatch.delenv("GATE_CANONICAL_DIR", raising=False)
    _write_core_files(tmp_path, content="# 이 저장소 전용 값\nprint(1)\n")
    monkeypatch.setattr(cgd, "_REPO_ROOT", tmp_path)
    assert cgd.main() == 1


def test_main_does_not_scan_itself_for_self_reference():
    """check_gate_drift.py 자신의 특정 저장소 지시 정규식 정의 줄은 검사 대상에서
    빠진다 — 그 줄 자체가 패턴 문자열을 담고 있어(정의하려면 적어야 한다) 자기
    자신을 스캔하면 항상 자기 위반으로 걸린다."""
    assert "scripts/check_gate_drift.py" not in cgd._SELF_REFERENCE_TARGETS
