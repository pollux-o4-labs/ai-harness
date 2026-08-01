#!/usr/bin/env python3
# BLUF: ai-harness 게이트 서브커맨드 디스패처 — 설치된 단일 CLI가 각 게이트 모듈의 main으로 라우팅한다(로직은 각 모듈이 정본).
"""ai-harness CLI 진입점.

`ai-harness <command> [args...]` → 해당 게이트 모듈의 `main(remaining_args)`.
서브커맨드는 게이트 모듈 하나에 1:1 대응한다 — 이 파일은 라우팅만 하고 판정
로직은 대상 모듈이 정본이다(중복 정의 금지).
"""
from __future__ import annotations

import importlib
import sys

# 서브커맨드 선언 테이블(정본) — (이름, usage 한 줄 설명, 게이트 대상 여부,
# 모듈 경로). usage 문자열·게이트 판정(apply_target_config 대조)·디스패치가
# 전부 이 테이블 하나에서 나온다 — 예전엔 서브커맨드가 늘 때마다 이 세 곳을
# 손으로 맞춰야 했다(손동기화). 모듈은 문자열 경로로 두고 importlib로 부른다
# — 서브커맨드 하나 실행에 다른 무거운 모듈까지 끌려오지 않게 하는 지연 로딩
# 설계를 그대로 유지한다.
_COMMANDS: tuple[tuple[str, str, bool, str], ...] = (
    ("check-pr", "PR 본문 구조·분량 게이트", True, "ai_harness.check_pr_body"),
    ("check-doc", "문서 폼(줄 예산) 게이트", True, "ai_harness.check_doc_form"),
    ("gen-readmes", "BLUF 기반 README 자동 생성", True, "ai_harness.gen_readmes"),
    (
        "gen-pr-template",
        "REQUIRED_CHECKS 등에서 PR 템플릿 생성(--check로 드리프트 감시)",
        True,
        "ai_harness.gen_pr_template",
    ),
    (
        "check-git-state",
        "미커밋을 지우는 git 명령 차단(링크 워크트리 한정)",
        True,
        "ai_harness.check_git_state",
    ),
    ("install-hooks", "git 훅 설치", False, "ai_harness.install_hooks"),
    (
        "install-agents",
        "리뷰어 에이전트 템플릿 설치(.claude/agents/)",
        False,
        "ai_harness.install_agents",
    ),
    (
        "install-rules",
        "공용 규칙 조문 설치(.claude/rules/, --user면 홈)",
        False,
        "ai_harness.install_rules",
    ),
    (
        "relink-docs",
        "토픽 폴더 재편 시 마크다운 링크 재작성·--check로 깨진 링크 스캔",
        False,
        "ai_harness.relink_docs",
    ),
)

# 게이트 서브커맨드 이름 집합 — 대상 저장소의 gate_config가 끌 수 있는 대상.
_GATED_COMMANDS = frozenset(name for name, _help, gated, _module in _COMMANDS if gated)
# 이름 → 모듈 경로(디스패치용).
_MODULE_BY_COMMAND = {name: module for name, _help, _gated, module in _COMMANDS}


def _build_usage() -> str:
    """`_COMMANDS`에서 usage 텍스트를 렌더 — 이름 열 너비는 가장 긴 이름에
    맞춰 자동으로 정렬된다(하드코딩된 칸 수 없음)."""
    width = max(len(name) for name, *_ in _COMMANDS)
    lines = ["ai-harness <command> [args...]", "", "  -V, --version  설치된 판", "", "commands:"]
    lines.extend(f"  {name:<{width}}  {help_text}" for name, help_text, *_ in _COMMANDS)
    return "\n".join(lines) + "\n"


_USAGE = _build_usage()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if args[0] in ("-V", "--version"):
        # 설치본에서 판을 읽는다 — 소스에 상수로 또 적지 않는다. 두 자리에
        # 두면 손으로 맞춰야 하고, 읽는 코드가 없으면 어긋나도 안 걸린다.
        # 설치된 저장소가 "지금 어느 판을 쓰는가"를 물을 유일한 수단이다.
        from importlib.metadata import version
        print(version("ai-harness"))
        return 0
    cmd, rest = args[0], args[1:]

    # 게이트 서브커맨드는 대상 저장소의 gate_config로 동작한다 — config가 대상 값을
    # 번들 모듈에 얹고(오버레이) 끌 게이트 목록을 돌려준다. 대상이 이 게이트를
    # 껐으면 no-op(원칙: 기본 전부 켬, gate_config로 예외).
    if cmd in _GATED_COMMANDS:
        from ai_harness.config import apply_target_config
        if cmd in apply_target_config():
            return 0

    if cmd in _MODULE_BY_COMMAND:
        module = importlib.import_module(_MODULE_BY_COMMAND[cmd])
        # 도움말 usage 줄에 쓸 이름을 인자로 넘긴다 — 안 넘기면 argparse가 실행
        # 경로 파일명을 써서 어느 서브커맨드인지 사라진다. 이름의 정본은 위 테이블
        # 하나이고 모듈은 받은 값을 쓸 뿐이라 재서술이 안 생긴다.
        # **전역(sys.argv)을 거치지 않는다** — 이 저장소는 인자를 전역으로 넘기던
        # 우회를 이미 걷어냈고(진입점이 argv를 파라미터로 받게 바꾼 그 변경),
        # 같은 계약을 이름에도 그대로 적용한다.
        return module.main(rest, prog=f"ai-harness {cmd}")

    print(f"[ai-harness] 알 수 없는 명령: {cmd}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
