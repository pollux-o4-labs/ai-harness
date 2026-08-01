#!/usr/bin/env python3
# BLUF: 마커 쌍으로 감싼 자동생성 블록을 찾고·세고·갈아 끼우는 공유 유틸 — gen_readmes.py에서 뽑았다(README 전용으로 굳어 있던 부분만 인자화).
"""마커 splice 공유 유틸(stdlib only).

`gen_readmes.py`가 "정본 하나 → 생성물 주입 → 어긋남 게이트" 골격을 README
인덱스에 대해 이미 풀었다. 두 번째 소비처(공용 안내 블록, `gen_agents_common.py`)가
생기며 무엇이 공유되고 무엇이 갈리는지 드러났다:

  공유한다   마커 탐색(정규식 컴파일) · 개수 세기(중복 마커 가드) ·
             블록 안 내용 추출 · 마커 쌍 교체/끝에 덧붙이기 · 원자적 쓰기
  갈라 둔다  블록 **내용**이 손댄 것인지 판정하는 법 — README 인덱스는
             저장소마다 달라 형태로 추정하고, 공용 블록은 모든 저장소가 같은
             정본을 받으므로 정확 일치로 잰다. 이 판정은 각 소비 모듈이 진다.

`gen_readmes.py`는 이 모듈의 함수를 감싸는 얇은 래퍼를 유지한다(공개 이름·
동작 불변) — 기존 테스트가 그 이름들을 직접 부른다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable


def compile_markers(start: str, end: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """마커 문자열 쌍에서 줄 시작 앵커 정규식 쌍을 만든다.

    **줄 시작 앵커가 핵심이다** — 문장 중간 인용은 줄을 시작하지 않으므로 이
    앵커에 안 걸린다. 처방의 근거·실사고 상세는 check_doc_form.py의
    `_AUTOGEN_START`/`_AUTOGEN_END` 주석이 정본이다.
    """
    return (
        re.compile(r"^[ \t]*" + re.escape(start), re.MULTILINE),
        re.compile(r"^[ \t]*" + re.escape(end), re.MULTILINE),
    )


def marker_occurrences(
    content: str, start_re: re.Pattern[str], end_re: re.Pattern[str]
) -> tuple[int, int]:
    """START·END 마커가 줄 시작 앵커 기준으로 각각 몇 번 나타나는지.

    정상은 (0, 0)이거나 (1, 1)뿐이다 — 블록이 없거나, 온전한 한 쌍이거나.
    나머지는 사람이 봐야 할 상태다(쌍이 여럿이면 어느 게 최신인지 기계가 못
    가리고, 짝이 안 맞으면 고아 마커 뒤에 새 블록이 덧붙는다).
    """
    return (
        sum(1 for _ in start_re.finditer(content)),
        sum(1 for _ in end_re.finditer(content)),
    )


def extract_block(
    content: str, start_re: re.Pattern[str], end_re: re.Pattern[str]
) -> str | None:
    """마커 쌍 사이의 내용(마커 자신은 제외)을 반환한다. 쌍이 없거나 짝이
    안 맞으면 None — 호출측이 "판정할 블록 자체가 없다"로 다룬다."""
    start_m = start_re.search(content)
    if not start_m:
        return None
    end_m = end_re.search(content, start_m.end())
    if not end_m:
        return None
    return content[start_m.end():end_m.start()]


def splice(
    content: str, block: str, start_re: re.Pattern[str], end_re: re.Pattern[str]
) -> str:
    """마커 쌍이 있으면 그 쌍째로 `block`(자신의 마커를 포함한 완결 텍스트)으로
    갈아 끼우고, 없으면 기존 내용을 보존한 채 끝에 덧붙인다(비파괴).

    `block`은 항상 자신의 START/END 마커 줄을 포함해서 넘겨야 한다 —
    이 함수는 마커를 새로 찍지 않는다(마커 밖 텍스트는 소비자마다 형태가
    달라 이 함수가 모른다).
    """
    start_m = start_re.search(content)
    end_m = end_re.search(content, start_m.end()) if start_m else None
    if start_m and end_m:
        head = content[:start_m.start()].rstrip()
        tail = content[end_m.end():].lstrip()
        parts = [head, "", block.rstrip()]
        if tail:
            parts += ["", tail.rstrip()]
        return "\n".join(parts).rstrip() + "\n"
    # 마커 없는 기존 내용: 전체를 보존하고 블록을 뒤에 덧붙인다.
    return content.rstrip() + "\n\n" + block.rstrip() + "\n"


def write_lf(path: Path, content: str) -> None:
    """줄바꿈을 LF로 고정해 쓴다 — 생성물이 플랫폼마다 달라지면 안 된다.

    `Path.write_text`의 `newline` 인자는 3.10부터라 선언 하한(3.9)에서
    TypeError를 낸다. `open`의 같은 인자는 오래전부터 있어 그것을 쓴다.
    """
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def write_atomically(
    path: Path, content: str, write: Callable[[Path, str], None] = write_lf
) -> None:
    """같은 폴더 임시 파일에 쓴 뒤 제자리 교체한다 — 대상은 늘 옛 내용이거나 새
    내용이고, 잘린 중간 상태가 될 수 없다.

    `write_text`는 원자적이지 않다 — 열기는 성공했는데 디스크가 차거나 I/O가
    끊기면 그 파일이 반쪽으로 남는다. 임시 파일을 **같은 폴더**에 두는 것이
    핵심이다(다른 파일시스템이면 교체가 원자적이지 않다).

    `write` 인자를 받는 이유: 호출측 모듈이 자기 전역 이름(예:
    `gen_readmes._write_lf`)을 통해 이 함수를 부르면, 그 이름을 테스트가
    monkeypatch해 쓰기 실패를 흉내낼 수 있다 — 이 함수 자체가 `write_lf`를
    직접 하드코딩해 부르면 그 우회로가 막힌다.

    실패하면 임시 파일을 치우고 예외를 그대로 올린다 — 대상은 손대지 않은 채다.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp, content)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
