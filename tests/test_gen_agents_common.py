# BLUF: gen_agents_common의 정본 주입·정확 일치 손편집 검출·멱등·마커 없음/중복 처리·--check 드리프트를 검증.
"""tests/test_gen_agents_common.py — AGENTS.md 공용 안내 주입기 단위테스트.

DB도 LLM(언어모델)도 안 쓴다 — 순수 파일 조작이라 어디서 돌려도 같은 결과다.

README 인덱스(gen_readmes)와 달리 이 블록은 모든 저장소가 같은 정본을 받으므로
손편집 판정이 형태 추정이 아니라 **정확 일치**다 — 그 차이를 고정하는 시험이
`test_prose_edit_inside_block_is_detected` 계열이다(README 쪽 형태 판정은
tests/test_gen_readmes_guard.py가 이미 지킨다).
"""
from __future__ import annotations

from pathlib import Path

import ai_harness.gen_agents_common as gac

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --- 블록 내용 ------------------------------------------------------------


def test_build_block_contains_all_six_axes():
    block = gac.build_block()
    for axis in ("기능", "비기능", "확장성", "유지보수성", "관측가능성", "사용성"):
        assert axis in block, f"{axis} 축이 블록에 없다"


def test_build_block_is_wrapped_in_markers():
    block = gac.build_block()
    assert block.startswith(gac.MARK_START)
    assert block.rstrip("\n").endswith(gac.MARK_END)


# --- 주입: 마커 없는 기존 파일은 끝에 덧붙인다 -------------------------------


def test_compose_appends_block_when_no_markers_present():
    """마커가 없으면 기존 내용을 보존하고 끝에 덧붙인다(비파괴) — 있는 내용을
    밀어내지 않는다."""
    existing = "# AGENTS.md\n\n손으로 쓴 저장소 고유 안내.\n"
    result = gac.compose(existing)
    assert "손으로 쓴 저장소 고유 안내." in result
    assert gac.MARK_START in result
    assert result.index("손으로 쓴 저장소 고유 안내.") < result.index(gac.MARK_START)


def test_compose_handles_missing_file():
    """파일 자체가 없으면(content=None) 블록만 낸다."""
    result = gac.compose(None)
    assert result == gac.build_block()


# --- 주입: 마커 있는 기존 파일은 그 쌍만 교체한다 ----------------------------


def test_compose_replaces_existing_block_and_preserves_surroundings():
    head = "# AGENTS.md\n\n앞쪽 손편집.\n"
    tail = "뒤쪽 손편집.\n"
    old_block = "\n".join([gac.MARK_START, "", "## 낡은 내용", "", gac.MARK_END])
    existing = head + "\n" + old_block + "\n\n" + tail

    result = gac.compose(existing)

    assert "앞쪽 손편집." in result
    assert "뒤쪽 손편집." in result
    assert "낡은 내용" not in result
    assert "산출물 판정 축" in result


# --- 멱등 ------------------------------------------------------------------


def test_running_twice_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n\n저장소 고유 내용.\n", encoding="utf-8")

    assert gac.main(["--root", str(tmp_path)]) == 0
    first = target.read_text(encoding="utf-8")

    assert gac.main(["--root", str(tmp_path)]) == 0
    second = target.read_text(encoding="utf-8")

    assert first == second, "두 번째 실행이 결과를 바꿨다 — 멱등이 아니다"
    assert "저장소 고유 내용." in second, "저장소 고유 내용이 보존되지 않았다"


def test_check_passes_after_injection(tmp_path):
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n", encoding="utf-8")
    assert gac.main(["--root", str(tmp_path)]) == 0
    assert gac.main(["--root", str(tmp_path), "--check"]) == 0


# --- 손편집 검출: 정확 일치(형태 추정이 아니다) ------------------------------


def test_handwritten_edit_none_when_block_matches_canonical():
    content = "머리말.\n\n" + gac.build_block()
    assert gac.handwritten_edit(content) is None


def test_handwritten_edit_detects_any_change_not_just_shape_violation():
    """README 인덱스는 형태(불릿·헤딩)를 벗어나야 손편집으로 잡히지만, 이
    블록은 형태를 지킨 채(불릿 그대로) 문구만 바꿔도 잡혀야 한다 — 정확
    일치라서다."""
    tampered_content = gac.build_block().replace("기능 — 하려던 일이 되는가",
                                                   "기능 — 손으로 고친 문구")
    assert gac.handwritten_edit(tampered_content) is not None


def test_handwritten_edit_none_when_no_block_present():
    assert gac.handwritten_edit("아무 내용.\n") is None


def test_run_aborts_without_writing_when_block_hand_edited(tmp_path, capsys):
    target = tmp_path / gac.TARGET_RELPATH
    tampered = gac.build_block().replace(
        "기능 — 하려던 일이 되는가", "기능 — 손으로 고친 문구"
    )
    target.write_text(tampered, encoding="utf-8")

    rc = gac.main(["--root", str(tmp_path)])

    assert rc == gac.HANDWRITTEN_ABORT
    assert target.read_text(encoding="utf-8") == tampered, "멈춘다고 해놓고 썼다"
    err = capsys.readouterr().err
    assert "손으로 고친 문구" in err, "무엇이 사라질지 안 알렸다"


def test_check_fails_when_block_hand_edited(tmp_path):
    """--check 모드에서도 손편집은 위반이지 조용한 통과가 아니다."""
    target = tmp_path / gac.TARGET_RELPATH
    tampered = gac.build_block().replace(
        "기능 — 하려던 일이 되는가", "기능 — 손으로 고친 문구"
    )
    target.write_text(tampered, encoding="utf-8")
    assert gac.main(["--root", str(tmp_path), "--check"]) == gac.HANDWRITTEN_ABORT


# --- 정본 갱신 vs 손편집: 둘 다 "블록이 정본과 다르다"지만 다른 사건이다 -------
#
# 회귀(적대검증 BLOCKER): `handwritten_edit`가 "블록 내용 대 지금 `_CONTENT`"
# 하나로만 비교하면, 아무도 블록을 안 건드렸는데 정본만 바뀐 경우까지
# 손편집으로 오판해 멈춘다. 주입 시점 해시(마커 안 `hash=` 주석)로 "이 도구가
# 마지막으로 쓴 그대로인가"를 재야 이 둘을 가른다 — 정본이 그 뒤 바뀌어도
# 해시가 그대로면 손편집이 아니라 그냥 낡음이다.


def test_canon_update_without_hand_edit_does_not_abort_and_updates_quietly(tmp_path, monkeypatch):
    """정본만 바뀌고 블록은 아무도 안 건드렸으면, 손편집으로 오판해 멈추면
    안 된다 — 새 정본으로 조용히 갱신해야 한다."""
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n", encoding="utf-8")

    monkeypatch.setattr(gac, "_CONTENT", "## 산출물 판정 축\n\n- 옛 축 — 옛 문구.")
    assert gac.main(["--root", str(tmp_path)]) == 0
    assert "옛 축" in target.read_text(encoding="utf-8")

    monkeypatch.setattr(gac, "_CONTENT", "## 산출물 판정 축\n\n- 새 축 — 새 문구.")
    rc = gac.main(["--root", str(tmp_path)])

    assert rc == 0, "정본 갱신만 있었는데 손편집으로 오판해 멈췄다(적대검증 BLOCKER 회귀)"
    updated = target.read_text(encoding="utf-8")
    assert "새 축" in updated
    assert "옛 축" not in updated


def test_canon_update_without_hand_edit_reports_drift_not_handwritten_under_check(
    tmp_path, monkeypatch
):
    """--check도 같은 사건을 같은 눈으로 봐야 한다 — DRIFT(재생성하면 풀림)여야
    하고 HANDWRITTEN_ABORT(사람이 봐야 함)로 새면 안 된다."""
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n", encoding="utf-8")

    monkeypatch.setattr(gac, "_CONTENT", "## 산출물 판정 축\n\n- 옛 축 — 옛 문구.")
    gac.main(["--root", str(tmp_path)])

    monkeypatch.setattr(gac, "_CONTENT", "## 산출물 판정 축\n\n- 새 축 — 새 문구.")
    rc = gac.main(["--root", str(tmp_path), "--check"])

    assert rc == gac.DRIFT
    assert rc != gac.HANDWRITTEN_ABORT


def test_hand_edit_after_canon_update_is_still_caught(tmp_path, monkeypatch):
    """정본 갱신을 눈감아주는 길을 열어도, 실제 손편집까지 같이 눈감으면
    안 된다 — 해시가 실제로 안 맞을 때는 여전히 멈춰야 한다."""
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n", encoding="utf-8")
    gac.main(["--root", str(tmp_path)])  # 정상 주입(해시 포함).

    content = target.read_text(encoding="utf-8")
    tampered = content.replace("기능 — 하려던 일이 되는가", "기능 — 손으로 고친 문구")
    target.write_text(tampered, encoding="utf-8")

    # 이 시점에 정본도 같이 바뀌었다고 해서 손편집 검출이 흐려지면 안 된다.
    monkeypatch.setattr(gac, "_CONTENT", gac._CONTENT + "\n- 새 축 — 새 문구.")

    rc = gac.main(["--root", str(tmp_path)])

    assert rc == gac.HANDWRITTEN_ABORT
    assert target.read_text(encoding="utf-8") == tampered, "멈춘다고 해놓고 썼다"


# --- 마커 쌍이 온전하지 않으면 쓰기 전에 멈춘다 ------------------------------


def test_duplicate_marker_pairs_abort_before_writing(tmp_path):
    block = gac.build_block()
    before = block + "\n" + block
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text(before, encoding="utf-8")

    rc = gac.main(["--root", str(tmp_path)])

    assert rc == gac.DUPLICATE_MARKERS
    assert target.read_text(encoding="utf-8") == before, "이상 상태인데 파일을 썼다"


def test_unpaired_marker_aborts_before_writing(tmp_path):
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text(f"{gac.MARK_START}\n### 문서\n", encoding="utf-8")

    rc = gac.main(["--root", str(tmp_path)])

    assert rc == gac.DUPLICATE_MARKERS


# --- --check 드리프트 --------------------------------------------------------


def test_check_fails_when_file_missing(tmp_path):
    assert gac.main(["--root", str(tmp_path), "--check"]) == gac.DRIFT


def test_check_does_not_write_file_on_missing(tmp_path):
    gac.main(["--root", str(tmp_path), "--check"])
    assert not (tmp_path / gac.TARGET_RELPATH).exists()


def test_check_fails_when_block_absent_from_existing_file(tmp_path):
    target = tmp_path / gac.TARGET_RELPATH
    target.write_text("# AGENTS.md\n\n블록이 아직 없다.\n", encoding="utf-8")
    assert gac.main(["--root", str(tmp_path), "--check"]) == gac.DRIFT


def test_no_arg_writes_and_creates_parent_dirs(tmp_path):
    root = tmp_path / "nested"
    assert gac.main(["--root", str(root)]) == 0
    assert (root / gac.TARGET_RELPATH).is_file()


# --- 실제 저장소 드리프트 self-test(배선, gen_pr_template과 동형) --------------


def test_repo_agents_md_has_no_drift():
    """이 저장소 자신의 AGENTS.md에 --check를 실제로 태워 exit 0인지 —
    도그푸딩을 pytest에 배선한다. 정본(`_CONTENT`)이 바뀌면 여기서 fail해,
    별도 CI·훅 없이 uv run pytest 한 번에 흡수된다."""
    assert gac.main(["--check", "--root", str(_REPO_ROOT)]) == 0
