#!/usr/bin/env python3
# BLUF: ai-harness 게이트 서브커맨드 디스패처 — 설치된 단일 CLI가 각 게이트 모듈의 main으로 라우팅한다(로직은 각 모듈이 정본).
"""ai-harness CLI 진입점.

`ai-harness <command> [args...]` → 해당 게이트 모듈의 `main(remaining_args)`.
서브커맨드는 게이트 모듈 하나에 1:1 대응한다 — 이 파일은 라우팅만 하고 판정
로직은 대상 모듈이 정본이다(중복 정의 금지).
"""
from __future__ import annotations

import sys

_USAGE = """\
ai-harness <command> [args...]

commands:
  check-pr       PR 본문 구조·분량 게이트
  check-doc      문서 폼(줄 예산) 게이트
  gen-readmes    BLUF 기반 README 자동 생성
  install-hooks  git 훅 설치
  install-agents 리뷰어 에이전트 템플릿 설치(.claude/agents/)
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    cmd, rest = args[0], args[1:]

    # 게이트 서브커맨드는 대상 저장소의 gate_config로 동작한다 — config가 대상 값을
    # 번들 모듈에 얹고(오버레이) 끌 게이트 목록을 돌려준다. 대상이 이 게이트를
    # 껐으면 no-op(원칙: 기본 전부 켬, gate_config로 예외).
    if cmd in ("check-pr", "check-doc", "gen-readmes"):
        from ai_harness.config import apply_target_config
        if cmd in apply_target_config():
            return 0

    if cmd == "check-pr":
        from ai_harness.check_pr_body import main as _m
        return _m(rest)
    if cmd == "check-doc":
        from ai_harness.check_doc_form import main as _m
        return _m(rest)
    if cmd == "gen-readmes":
        # gen_readmes.main()은 argv를 안 받고 sys.argv를 파싱한다 — 서브커맨드를
        # 벗겨 넘긴다(디스패처가 argv를 정규화).
        from ai_harness.gen_readmes import main as _m
        sys.argv = ["ai-harness gen-readmes", *rest]
        return _m()
    if cmd == "install-hooks":
        from ai_harness.install_hooks import main as _m
        return _m(rest)
    if cmd == "install-agents":
        from ai_harness.install_agents import main as _m
        return _m(rest)

    print(f"[ai-harness] 알 수 없는 명령: {cmd}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
