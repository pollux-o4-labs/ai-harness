#!/usr/bin/env python3
# BLUF: 토픽 폴더 재편(문서를 폴더로 옮길 때) 시 이동 대상을 가리키던 마크다운 링크를 결정적으로 재작성하고(mv 후), --check로 깨진 상대링크를 스캔하는 유틸(stdlib only, LLM 0).
"""문서 재편 링크 재작성기 — 토픽 폴더 그룹핑 도구.

평평한 디렉터리를 토픽 폴더로 묶으면(`topic-folders-when-scope-overlaps.md`
참조) 그 문서를 가리키던 상대링크를 전수 갱신해야 한다. 손으로 하면 누락이
나므로 결정적으로 처리한다.

## 재작성 알고리즘 (rewrite 모드)

move_map(old_repo_rel -> new_repo_rel, posix)를 받아, 추적 중인 모든 .md의
마크다운 링크를 균일 식으로 재작성한다.

    각 링크 L(path P, anchor A):
      target_old_abs = normalize(dirname(S_old)/P)   # 링크가 쓰인 원위치 기준
      target_new_abs = move_map.get(target_old_abs, target_old_abs)
      new_P = relpath(target_new_abs, dirname(S_new))

이 한 식이 (1)이동 대상을 가리키는 인바운드 링크와 (2)이동한 파일이 비이동
대상을 가리키는 아웃바운드 링크(source가 깊어져 ../ 증감)를 동시에 바로잡는다.
소스도 타깃도 안 움직인 링크는 건드리지 않는다(무의미 churn 방지).

이 모듈은 stdlib만 쓴다 — 훅 실행 환경에 이 패키지 밖 의존성이 없어야 해서
전체 마크다운 파서 대신 좁은 정규식으로 링크·펜스만 인식한다.

## 알려진 한계 (반드시 --check로 보완)

링크 정규식은 `[label](target)`이 **한 줄에** 있어야 매칭한다. 소프트랩으로
`[label`과 `](target)`이 다른 줄에 나뉜 링크는 rewrite가 **놓친다**. 그래서
mv+rewrite 후 반드시 `--check`로 깨진 상대링크를 재스캔하라 — `--check`는
라벨 무관 정규식이라 소프트랩 타깃도 잡는다.

## 사용

    # 1) 재작성: git mv 를 먼저 한 뒤(파일이 new 위치에 있어야 함), move_map JSON 지정
    ai-harness relink-docs <move_map.json>
    #    move_map.json = {"docs/adr/0002-x.md": "docs/adr/cross-repo/0002-x.md", ...}

    # 2) 검증: 이동 후 깨진 상대링크 전수 스캔(소프트랩 포함) — 0이어야 함
    ai-harness relink-docs --check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from ai_harness.config import target_root
from ai_harness.line_shapes import is_fence_line

_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)\s]+)\)")
_EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
# --check용: 라벨 무관(소프트랩 대응) 상대경로 타깃 스캐너.
_RELTARGET_RE = re.compile(r"\]\((\.\.?/[^)\s#]*)")


def _tracked_md(root: Path) -> list[str]:
    """root 아래 git 추적 중인 .md 상대경로(posix) 목록.

    `-z`(NUL 구분자)로 뽑는다 — 개행 구분 기본 출력은 비ASCII·탭·백슬래시·
    큰따옴표가 든 경로를 C 방식으로 quote한다(예: `"docs/\355\225\234...md"`).
    quote를 안 풀고 그 문자열을 그대로 경로로 쓰면 존재하지 않는 경로가 되어
    파일 열기가 크래시한다(실측: 형제 저장소는 문서가 대부분 한글 이름이라
    첫 실행에서 죽는다). `core.quotepath=false`는 비ASCII만 풀고 탭·백슬래시·
    큰따옴표 quote는 그 설정과 무관하게 남는다(실측 확인) — `-z`는 애초에
    quote 자체가 없어 이 문제를 근본에서 없앤다(gen_readmes.py의 같은 처방과
    동형).
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=str(root), capture_output=True, text=True, check=False,
    ).stdout
    # -z 출력은 NUL로 끝나는 토큰열이다 — 마지막 토큰은 트레일링 NUL이 만든
    # 빈 문자열이라 버린다(gen_readmes.py의 같은 파싱과 동형).
    tokens = out.split("\0")
    # 이 분기의 False측은 도달 불가 — git의 -z 출력은 결과가 없으면 빈 문자열,
    # 있으면 매 항목이 NUL로 끝나 split 결과가 항상 빈 문자열로 끝난다(방어
    # 코드로 남기고 시험으로 강제하지 않는다).
    if tokens and tokens[-1] == "":
        tokens.pop()
    return tokens


def normalize(path: str) -> str:
    """posix 경로에서 ..·. 을 접어 정규화(확장자 유지)."""
    parts: list[str] = []
    for seg in PurePosixPath(path).parts:
        if seg == "..":
            if parts:
                parts.pop()
        elif seg not in (".", ""):
            # 이 분기의 False측(seg가 "."·"")은 PurePosixPath가 .parts를 만들 때
            # 이미 그 세그먼트를 자체 소거해 도달 불가 — 방어 코드로 남기고
            # 시험으로 강제하지 않는다(시험 불가능한 대상을 억지로 만들면 위장).
            parts.append(seg)
    return "/".join(parts)


def relpath(target: str, start_dir: str) -> str:
    """target(repo-rel)을 start_dir(repo-rel) 기준 상대경로로. posix."""
    t = target.split("/")
    s = [x for x in start_dir.split("/") if x]
    i = 0
    while i < len(s) and i < len(t) and s[i] == t[i]:
        i += 1
    rel = [".."] * (len(s) - i) + t[i:]
    return "/".join(rel) if rel else "."


def rewrite_file(path: Path, s_old: str, s_new: str, move_map: dict[str, str]) -> int:
    text = path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    in_fence = False
    changed = 0
    src_dir_old = str(PurePosixPath(s_old).parent)
    src_dir_new = str(PurePosixPath(s_new).parent)
    src_dir_old = "" if src_dir_old == "." else src_dir_old
    src_dir_new = "" if src_dir_new == "." else src_dir_new

    for line in text.split("\n"):
        if is_fence_line(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        def repl(m: re.Match) -> str:
            nonlocal changed
            label, target = m.group(1), m.group(2)
            if _EXTERNAL_RE.match(target) or target.startswith("#"):
                return m.group(0)
            path_part, sep, anchor = target.partition("#")
            if not path_part:
                # 바로 위 target.startswith("#") 검사가 이미 path_part가 빈
                # 유일한 경로를 막아 도달 불가 — 그 검사가 독립적으로 바뀌어도
                # 안전하도록 남긴 방어 코드다(시험으로 강제하지 않는다).
                return m.group(0)
            base = f"{src_dir_old}/{path_part}" if src_dir_old else path_part
            target_old_abs = normalize(base)
            if s_old == s_new and target_old_abs not in move_map:
                return m.group(0)
            target_new_abs = move_map.get(target_old_abs, target_old_abs)
            new_p = relpath(target_new_abs, src_dir_new)
            new_target = new_p + sep + anchor if sep else new_p
            if new_target != target:
                changed += 1
                return f"[{label}]({new_target})"
            return m.group(0)

        out_lines.append(_LINK_RE.sub(repl, line))

    if changed:
        path.write_text("\n".join(out_lines), encoding="utf-8", newline="\n")
    return changed


def cmd_rewrite(root: Path, move_map_path: str) -> int:
    with open(move_map_path, encoding="utf-8") as f:
        move_map = json.load(f)
    new_to_old = {v: k for k, v in move_map.items()}
    total = 0
    for rel in _tracked_md(root):
        old_rel = new_to_old.get(rel, rel)
        n = rewrite_file(root / rel, old_rel, rel, move_map)
        if n:
            print(f"  {n:3d}  {rel}")
            total += n
    print(f"[relink_docs] 총 {total}개 링크 재작성")
    print("[relink_docs] 이제 반드시 --check 로 깨진 링크(소프트랩 포함)를 재스캔하라.")
    return 0


def cmd_check(root: Path) -> int:
    """이동 후 깨진 상대링크 전수 스캔(라벨 무관 → 소프트랩 타깃도 잡음)."""
    broken: list[tuple[str, int, str]] = []
    for rel in _tracked_md(root):
        base = os.path.dirname(rel)
        with open(root / rel, encoding="utf-8") as f:
            content = f.read()
        for i, line in enumerate(content.split("\n"), 1):
            for m in _RELTARGET_RE.finditer(line):
                tgt = m.group(1)
                resolved = os.path.normpath(os.path.join(base, tgt))
                if not (root / resolved).exists():
                    broken.append((rel, i, tgt))
    for f, i, t in broken:
        print(f"  BROKEN {f}:{i}  {t}", file=sys.stderr)
    print(f"[relink_docs] 깨진 상대링크: {len(broken)}")
    return 1 if broken else 0


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog=prog,
        description="문서 재편 링크 재작성기 — 마크다운 링크 재작성(rewrite)과 깨진 링크 스캔(--check)",
    )
    ap.add_argument(
        "--root", default=None, help="저장소 루트 경로(기본: 대상 저장소 git 루트)"
    )
    ap.add_argument(
        "--check", action="store_true",
        help="이동 후 깨진 상대링크 전수 스캔(exit 1 = 발견, move_map 인자 무시)",
    )
    ap.add_argument(
        "move_map", nargs="?", metavar="MOVE_MAP_JSON",
        help="rewrite 모드 — {old_repo_rel: new_repo_rel} JSON 경로",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else target_root()

    if args.check:
        return cmd_check(root)
    if args.move_map:
        return cmd_rewrite(root, args.move_map)
    ap.error("MOVE_MAP_JSON 또는 --check 중 하나가 필요하다")


if __name__ == "__main__":
    sys.exit(main())
