#!/usr/bin/env python3
# BLUF: core 게이트 스크립트가 형제 저장소의 정본과 바이트 동일한지 비교하고, 특정 저장소를 가리키는 서술이 core에 남았는지 보는 룰 게이트(stdlib only, LLM 0).
"""게이트 core 드리프트 검사.

`check_pr_body.py`·`check_doc_form.py`·`gen_readmes.py`(core)는 어느 저장소에서
읽어도 바이트가 같아야 한다 — 저장소별 값은 `gate_config.py`(이 비교에서 뺀다)로
이미 뽑았기 때문이다. 이 스크립트 자신도 core라 비교 대상이다(드리프트
검사기가 스스로 갈라지면 검사기를 못 믿는다).

**형제 저장소 경로가 없으면 skip이다(fail 아님)** — 단독으로 clone된 상태일
수 있고, 그건 실패가 아니라 비교할 대상이 없는 것뿐이다. 경로는 환경변수
`GATE_CANONICAL_DIR`로 받는다.

특정 저장소 지시 검사(형제 경로 유무와 무관하게 항상 실행)는 core 파일에
`_SELF_REFERENCE` 패턴에 해당하는 표현이 남았는지 본다 — core는 바이트가
같아야 하므로 그런 표현이 있으면 정의상 어느 한쪽에서는 거짓이 된다(저장소별
사실은 gate_config.py로 뺀다).

**모드**:
  python scripts/check_gate_drift.py   # GATE_CANONICAL_DIR 있으면 바이트 비교도,
                                        # 없으면 특정 저장소 지시 검사만(exit 1 = 위반)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# 바이트 비교 대상(core) — gate_config.py는 뺀다. 그 파일은 저장소마다
# 다르라고 만든 것이라 다른 것 자체가 드리프트가 아니다.
CORE_FILES: tuple[str, ...] = (
    "scripts/check_pr_body.py",
    "scripts/check_doc_form.py",
    "scripts/gen_readmes.py",
    "scripts/check_gate_drift.py",
)

# 특정 저장소 지시 검사 대상 — 이 스크립트 자신은 뺀다. 아래 패턴 정의 줄
# 자체가 그 문구들을 담고 있어(검사하려면 적어야 하니) 자기 자신을 스캔하면
# 항상 자기 위반으로 걸린다 — 프로필터가 자기 소스에 금칙어 목록을 담는 것과
# 같은 이유로, 이 파일은 검사 대상이 아니라 검사 정의 그 자체다.
_SELF_REFERENCE_TARGETS: tuple[str, ...] = (
    "scripts/check_pr_body.py",
    "scripts/check_doc_form.py",
    "scripts/gen_readmes.py",
)

# core 파일에 남으면 안 되는 특정 저장소 지시 표현 — core는 어느 저장소에서
# 읽어도 바이트가 같아야 하므로, 이런 서술은 그 저장소에서만 참인 주장이라
# core에 있으면 안 된다(다른 저장소로 복사되는 순간 거짓이 된다).
_SELF_REFERENCE = re.compile(r"이 저장소|우리 레포|이 레포")


def check_self_reference(path: Path) -> list[str]:
    """core 파일 하나에 특정 저장소 지시 표현이 있는지 본다."""
    violations: list[str] = []
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if _SELF_REFERENCE.search(line):
            violations.append(
                f"{path}:{i}: core 파일에 특정 저장소 지시 표현이 남음 — "
                f"core는 어느 저장소에서 읽어도 바이트가 같아야 하므로 "
                f"특정 저장소를 가리키는 서술을 담으면 안 된다. 저장소별 "
                f"사실은 gate_config.py로 빼라."
            )
    return violations


def check_byte_identical(canonical_dir: Path) -> list[str]:
    """core 파일이 형제 저장소의 정본과 바이트 동일한지 본다."""
    violations: list[str] = []
    for rel in CORE_FILES:
        mine = _REPO_ROOT / rel
        theirs = canonical_dir / rel
        if not mine.is_file():
            violations.append(f"{rel}: 대상 경로에 파일이 없음")
            continue
        if not theirs.is_file():
            violations.append(f"{rel}: 정본 저장소({canonical_dir})에 파일이 없음")
            continue
        if mine.read_bytes() != theirs.read_bytes():
            violations.append(
                f"{rel}: 정본({canonical_dir})과 바이트가 다르다 — core는 "
                f"복사본이라 갈라지면 안 된다. `diff {mine} {theirs}`로 확인하라."
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    violations: list[str] = []
    for rel in _SELF_REFERENCE_TARGETS:
        path = _REPO_ROOT / rel
        if path.is_file():
            violations.extend(check_self_reference(path))

    canonical = os.environ.get("GATE_CANONICAL_DIR")
    if canonical:
        violations.extend(check_byte_identical(Path(canonical)))
    else:
        print(
            "[check_gate_drift] GATE_CANONICAL_DIR 미설정 — 바이트 비교는 "
            "skip(특정 저장소 지시 검사만 실행).",
            file=sys.stderr,
        )

    if not violations:
        print("[check_gate_drift] 통과.")
        return 0

    print(f"[check_gate_drift] 드리프트 {len(violations)}건:", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
