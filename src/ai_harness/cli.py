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
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    cmd, rest = args[0], args[1:]

    # 게이트 서브커맨드는 **대상 저장소의 gate_config**로 동작한다. CLI는 매 호출이
    # 새 프로세스라, 진입점에서 대상 값을 번들 모듈에 덮어씌운 뒤 게이트를 지연
    # import(아래 분기)하면 게이트의 `from ...gate_config import`가 그 덮인 값을
    # 읽는다 — 게이트 코드는 안 바꾼다. 대상에 없는 값은 번들 기본을 그대로 상속.
    if cmd in ("check-pr", "check-doc", "gen-readmes"):
        from ai_harness import config as _config
        import ai_harness.gate_config as _gc
        _target = _config.load_target_config()
        if _target is not _gc:
            for _name in ("JARGON_TERMS", "EXEMPT_SECTIONS", "EXTRA_AUTOGEN_MARKERS",
                          "RULE_DOC_AUTHORING", "RULE_REVIEW_EVIDENCE",
                          "build_exempt_shape", "rule_cite"):
                if hasattr(_target, _name):
                    setattr(_gc, _name, getattr(_target, _name))
        if cmd in tuple(getattr(_target, "DISABLED_GATES", ())):
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

    print(f"[ai-harness] 알 수 없는 명령: {cmd}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
