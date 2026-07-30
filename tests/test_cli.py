# BLUF: 디스패처가 선언 테이블의 모든 서브커맨드를 실제로 부를 수 있는지 검증 — 모듈 경로가 문자열이라 정적 검사가 오타를 못 잡는다.
"""tests/test_cli.py — 서브커맨드 디스패처.

`cli._COMMANDS`가 모듈 경로를 **문자열**로 들고 `importlib`로 푼다. 그래서 경로에
오타가 나도 린트·임포트 시점엔 조용하고, 그 서브커맨드를 **실행할 때에야** 터진다.
그 공백을 여기서 메운다 — 테이블의 모든 항목을 실제로 임포트해 본다.

DB도 LLM(언어모델)도 안 쓴다.
"""
from __future__ import annotations

import sys

import importlib

import pytest

import ai_harness.cli as cli


@pytest.mark.parametrize("name,module_path", sorted(cli._MODULE_BY_COMMAND.items()))
def test_every_command_resolves_to_an_importable_main(name, module_path):
    """테이블의 모든 서브커맨드가 실제 모듈의 `main`으로 풀린다.

    문자열 경로라 오타가 실행 시점까지 숨는다 — 여기서 전부 한 번씩 푼다."""
    module = importlib.import_module(module_path)
    assert callable(module.main), f"{name} → {module_path}.main 이 없다"


def test_usage_lists_every_command():
    """도움말이 테이블에서 파생되므로 빠진 커맨드가 없어야 한다."""
    for name in cli._MODULE_BY_COMMAND:
        assert f"  {name}" in cli._USAGE, f"usage에 {name}이 없다"


def test_gated_commands_are_a_subset_of_declared_commands():
    """게이트 대상 집합이 테이블 밖 이름을 갖지 않는다 — 오타면 그 게이트가 안 꺼진다."""
    assert cli._GATED_COMMANDS <= set(cli._MODULE_BY_COMMAND)


def test_unknown_command_exits_two():
    assert cli.main(["frobnicate"]) == 2


def test_help_exits_zero():
    assert cli.main(["--help"]) == 0
    assert cli.main([]) == 0


@pytest.mark.parametrize("name", sorted(cli._MODULE_BY_COMMAND))
def test_subcommand_help_usage_shows_its_own_name(name, capsys):
    """서브커맨드 `--help`의 usage 줄에 그 서브커맨드 이름이 실제로 나온다.

    이름의 정본은 `cli._COMMANDS` 하나뿐이다(모듈은 재서술하지 않는다) —
    디스패치가 그 이름을 `prog` 인자로 넘기고 각 진입점이 받아 쓴다(argparse
    미사용인 check-doc도 같은 인자를 받아 자기 도움말에 찍는다).
    argparse는 `-h`에서 `SystemExit(0)`을 던지므로 그걸 받아준다."""
    try:
        rc = cli.main([name, "--help"])
    except SystemExit as e:
        rc = e.code
    assert rc == 0
    out = capsys.readouterr().out
    assert f"ai-harness {name}" in out, f"{name} --help usage에 이름이 안 보임: {out!r}"


def test_dispatch_does_not_touch_global_argv(monkeypatch, capsys):
    """디스패치가 전역 인자를 아예 건드리지 않는다.

    이름은 파라미터로 넘긴다 — 전역에 써 놓고 되돌리는 방식은 이 저장소가
    이미 걷어낸 우회이고, 되돌리기를 빠뜨리면 조용히 오염이 남는다.
    건드리지 않으면 되돌릴 것도 없다.

    정상 종료와 도움말(SystemExit) 두 경로를 다 본다."""
    original = ["/원래/자리/에서-부른-것", "무시되는-인자"]
    monkeypatch.setattr(sys, "argv", list(original))

    assert cli.main(["gen-pr-template", "--check"]) == 0
    assert sys.argv == original, "정상 종료 경로에서 전역 인자가 바뀌었다"

    with pytest.raises(SystemExit):
        cli.main(["check-pr", "--help"])
    capsys.readouterr()
    assert sys.argv == original, "도움말 경로에서 전역 인자가 바뀌었다"
