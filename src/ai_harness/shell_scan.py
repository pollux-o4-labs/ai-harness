#!/usr/bin/env python3
# BLUF: 셸 명령 문자열의 토큰화와 연산자 경계 분할(stdlib only, 의존성 0) — 두 게이트가 각자 구현하던 것을 한 자리로 모은 모듈.
"""셸 명령 스캔 — 토큰화와 세그먼트 분할.

`check_pr_body.py`(PR 본문 게이트)와 `check_git_state.py`(git 상태 가드)가 둘 다
훅으로 들어온 명령 문자열을 읽는다. 둘은 서로를 참조하지 않으며 이 모듈도 어느
쪽도 끌어들이지 않으므로 순환이 없다 — `line_shapes.py`와 같은 자리다.

**정책 중립이다.** 파싱 실패는 예외로 그대로 올린다. 두 호출자의 실패 정책이
정반대이기 때문이다 — git 가드는 못 읽으면 통과시키고(막으면 셸 전체가 멈춘다),
PR 게이트는 못 읽으면 리젝한다(우회할 수 있으면 게이트가 아니다). 그 판단을 이
모듈 안으로 넣지 마라.
"""
from __future__ import annotations

import shlex

# 세그먼트 경계가 되는 셸 연산자. 두 게이트가 각자 집합을 두었을 때 한쪽에만
# `&`가 있어 판정이 갈렸다 — 단일 앰퍼샌드로 이어진 뒤 명령의 인자를 앞 명령
# 것으로 오인했다(실측). 이 집합의 정본은 여기 하나다.
SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&"})


def tokenize(command: str) -> list[str]:
    """명령 문자열을 토큰으로 나누되 셸 연산자가 공백 없이 붙어 있어도 뗀다.

    `shlex.split`은 공백 분리 토크나이저라 셸 문법을 모른다 — `git reset --hard;
    git clean -fd`를 `['git','reset','--hard;',...]`로 잘라 `;`가 `--hard`에
    들러붙는다. 그러면 세그먼트가 안 갈리고 인자 판정이 통째로 어긋난다(실측
    회귀). `punctuation_chars=True`는 연산자를 떼되 따옴표 안(`-m "a; b"`)은
    보존하며 `#` 이후를 주석으로 인식한다.

    미닫힌 따옴표는 `ValueError`를 올린다 — 호출자가 자기 정책으로 해석한다.
    """
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def split_segments(argv: list[str]) -> list[list[str]]:
    """토큰 목록을 연산자 경계로 나눈다. 연산자 토큰 자체는 버린다."""
    seg: list[str] = []
    out: list[list[str]] = []
    for tok in argv:
        if tok in SHELL_OPERATORS:
            if seg:
                out.append(seg)
                seg = []
        else:
            seg.append(tok)
    if seg:
        out.append(seg)
    return out
