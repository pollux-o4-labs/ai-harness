#!/usr/bin/env python3
# BLUF: 변경된 .md가 유형별 폼(docs_format/*.md)의 줄 예산을 지키는지 판정하는 룰 게이트(stdlib only, LLM 0) — pre-commit 훅으로 커밋을 리젝한다.
"""문서 폼 게이트 — 줄 단위.

한 줄에 흐름을 통째로 우겨넣으면 파일이 비대해지고 검토가 안 된다(실측: 과도하게
긴 한 줄과 비대한 BLUF가 실존했다). 총량만 재면 이게 안 걸리므로
줄 단위로 잰다.

**예산 수치를 여기 하드코딩하지 않는다** — 정본은 `docs_format/<유형>.md`
폼이고 이 스크립트가 그걸 파싱해 쓴다. 골격을 폼과 코드 두 군데 두면 언젠가
어긋난다.

**모드**:
  ai-harness check-doc FILE...   # 지정 파일 검사(exit 1 = 위반)
  ai-harness check-doc --staged  # 스테이징된 .md만(pre-commit)

**레포별 설정은 `gate_config.py`에 있다** — 이 판정의 근거 조문을 리젝 메시지에
인용할지는 `gate_config.RULE_DOC_AUTHORING`이 정한다(문서 저작 규칙 문서가
없는 저장소는 공란이라 인용이 생략된다).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from ai_harness.gate_config import EXTRA_AUTOGEN_MARKERS, RULE_DOC_AUTHORING
from ai_harness.gate_config import rule_cite as _rule_cite

# CWD가 아니라 이 스크립트 자신의 위치에 앵커링한다 — CWD 상대였을 때 다른
# 디렉터리에서 불러오면 폼을 못 찾고, 그러면 아래 load_budgets가 빈 dict를
# 반환해 예산이 전부 None이 되어 검사를 통째로 건너뛰고 조용히 통과했다
# (회귀: 같은 파일이 CWD만 바꿔도 판정이 뒤집힘).
FORM_DIR = Path(__file__).resolve().parent / "docs_format"

# 폼에서 예산을 뽑는 패턴. 폼이 정본이므로 수치는 코드에 없다.
# 실제 폼 문구는 "100줄 · 산문 한 줄 80자 · BLUF 한 줄 100자(마커 제외)."이지
# "…이하" 접미사가 없다 — 접미사를 요구하면 4개 폼 전부 매칭 실패로 예산이
# 항상 빈 dict가 되어 게이트가 조용히 무력화된다(회귀 방지).
_BUDGET_PATS = {
    "line_chars": re.compile(r"산문 한 줄 (\d+)자"),
    "max_lines": re.compile(r"(\d+)줄"),
    "bluf_chars": re.compile(r"BLUF 한 줄 (\d+)자"),
}

# 줄 예산은 전 .md 공통 위생이다 — 유형 폼이 없어도 적용한다.
# 유형 폼이 있으면 그쪽 수치가 이긴다.
_GLOBAL_FORM = "rules"

# 주: gen_readmes.py 등에도 동일 상수를 둔다 — 이 스크립트는 stdlib only라
# (훅에서 별도 설치 없이 돈다) import로 합칠 수 없다.
_AGENT_CONFIG_NAMES = frozenset({"AGENTS.md", "CLAUDE.md"})

# 에이전트 정의가 사는 디렉터리. 파일명은 페르소나 이름이라 자유(reviewer.md 등)
# — 이름이 아니라 **디렉터리**가 유형이다. 유형명은 폼 파일명과 같아야 한다
# (load_budgets가 `docs_format/<유형>.md`를 찾는다).
_AGENT_DEF_DIR: tuple[str, str] = (".claude", "agents")
_AGENT_DEF_TYPE = "agent-def"

# 예산 면제 문서. **비어 있는 게 기본이다** — 길어야 정상인 문서(레퍼런스·
# 기록 등)가 관측되면 그때 경로를 여기 추가한다. 미리 채워두지 않는다.
# 이 목록의 정본은 이 파일이다. 등재 시 왜 면제인지 한 줄 주석을 붙일 것.
WHITELIST: frozenset[str] = frozenset()

# 금지된 문서 참조. `(참조하는 문서, 참조 대상)` 쌍이며 **비어 있는 게 기본이다.**
#
# 어휘를 미리 닫는 화이트리스트("이 유형은 저 유형만 참조 가능")는 실측으로
# 기각됐다 — 관계 종류가 많고 그중 상당수가 드물어 어휘가 안 닫힌다(상당
# 비율이 "기타"로 뭉개진다). 블랙리스트는 반대로 **안 닫혀도 된다**:
# 사람이 문서를 읽다 "이 참조는 왜 있나, 안 읽어도 되는데"를 짚었을 때만 그
# 쌍이 여기 쌓이고, 그 뒤로 같은 참조가 다시 나타나면 커밋이 막힌다.
#
# 등재 형식: (참조하는 문서 경로, 참조 대상 경로 또는 그 일부).
# 대상은 부분 문자열로 매칭한다 — 링크 경로·표기가 문서마다 달라서다.
# 등재 시 **왜 불필요한지** 한 줄 주석을 반드시 붙일 것. 근거 없는 금지는
# 다음 사람이 못 지운다.
FORBIDDEN_REFS: frozenset[tuple[str, str]] = frozenset()

_BLUF = re.compile(r"^>\s*\*\*BLUF:\*\*\s*")
_FENCE = re.compile(r"^\s*```")
_TABLE_ROW = re.compile(r"^\s*\|")
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# features 문서의 검증 참조 — `[✅ 파일::함수]`·`[⚠️ …]`·`[🔴 …]`. 테스트
# 함수명이라 표·코드펜스처럼 못 쪼갠다(GUIDE.md가 필수로 요구하는 몫). 줄
# 길이 측정에서 이 스팬만 뺀다 — 산문은 여전히 상한을 진다(남용 차단).
# **단 면제에는 상한이 있다** — `_strip_review_refs` 참고.
_REVIEW_REF = re.compile(r"\[(?:✅|⚠️|🔴)[^\]]*\]")

# 문장 종결 마침표 — 비숫자 뒤 `. ` + 그 뒤에 다음 문장(비공백)이 이어질 때.
# 이게 산문 줄 안에 있으면 한 줄에 문장이 여럿이라는 뜻이다(흐름 우겨넣기).
# - 앞이 숫자·마침표면 배제 → 소수(0.85)·번호(1. )·말줄임(`...`)이 안 걸린다.
# - 뒤가 공백 아니면 배제 → 코드(config.py)·경로가 안 걸린다.
# - 뒤가 줄 끝/참조뿐이면 배제 → "불변 서술. [✅ test]"는 한 문장이라 통과
#   (검증 참조를 뺀 measured가 "…. "로 끝나 다음 문장이 없다).
# 80자(길이 프록시)와 병존 — 이건 구조를 강제한다.
_SENTENCE_END = re.compile(r"(?<![0-9.])\. (?=\S)")

# 마크다운 헤딩(`## A. 환경` 등)은 산문 흐름이 아니라 구조 라벨이라 문장 규칙에서
# 뺀다 — 라벨의 `A.`가 문장 끝으로 오인돼(숫자 `1.`은 앞자리 숫자로 배제되지만
# 문자 라벨은 안 됨) 헤딩이 "문장 여럿"으로 오탐되는 것을 막는다. 길이 예산은
# 그대로 진다 — 라벨은 짧아야 한다.
_HEADING = re.compile(r"^\s*#{1,6}\s")

# 손으로 친 줄번호 좌표(`config.py:168`)를 금지한다 — 좌표는 위에 한 줄만 끼어도
# 밀려 편집마다 조용히 stale해진다. 심볼명/SHA-고정 경로로
# 가리키면 틀렸을 때 조회가 실패해 fail-loud가 된다.
# **현재상태 문서 전부**에 건다 — 코드의 지금 동작을 서술하므로 좌표가 살아있는
# 주장이다(features·rules·agents·루트 등). 날짜 박힌 기록만 면제한다: adr·history·
# review·test은 "그 시점의 위치"라 정당한 출처 근거다. denylist라 새 현재상태
# 유형이 생겨도 자동으로 걸린다(features만 걸던 allowlist는 자의적이라 뒤집음).
# 확장자 토큰이 콜론+숫자 앞에 붙어야만 매칭 → URL(`localhost:8765`)·타임스탬프
# (`16:55`)·심볼(`cli.py::main`)·SHA경로(`git show <sha>:path`)는 안 걸린다.
_COORD_EXEMPT_TYPES = frozenset({"adr", "history", "review", "test"})
_COORD = re.compile(r"[\w./-]+\.(?:py|md|sh|json|toml|ya?ml|lock|txt|cfg|ini):\d+")

# 자동생성 블록 경계. 이 안은 줄 길이 검사에서 면제한다 — 저자가 손댈 수 없는
# 몫을 예산에 넣으면 저자는 그 예산을 지킬 방법이 없다(고정 문구인 체크리스트를
# 예산에서 뺀 것과 같은 이유). 이 블록의 길이는 원본 문서의
# BLUF가 정하므로, 줄이려면 BLUF 상한으로 원본을 쳐야 한다 — 그쪽이 정본이다.
# 자동생성 블록 마커. core는 gen_readmes.py의 롤업 마커 하나만 안다 — 저장소가
# 자체 멱등 splice 도구를 갖췄으면 그 마커는 `gate_config.EXTRA_AUTOGEN_MARKERS`에
# 얹는다(repo별 특화 지점, core에 하드코딩하면 그 도구가 없는 저장소에 죽은
# 참조가 남는다). **마커가 늘면 이 튜플이나 EXTRA_AUTOGEN_MARKERS에만
# 추가한다** — "저자가 손댈 수 없는 몫을 저자 예산에 세지 않는다"는 원칙은
# 마커 종류와 무관하고, 정규식을 손으로 두 군데 고치게 두면 한쪽만 늘어난다.
_AUTOGEN_MARKERS: tuple[tuple[str, str], ...] = (
    ("BLUF-INDEX:START", "BLUF-INDEX:END"),      # gen_readmes 롤업
) + tuple(EXTRA_AUTOGEN_MARKERS)
# **줄 시작 앵커가 핵심이다.** 생성기가 찍는 마커는 언제나 그 줄의 유일한
# 내용이지만, 프로즈는 마커 문법을 문장 중간에 인용할 수 있다 — 실사고: 그런
# 인용 한 줄이 파일 끝까지를 면제시켜 위반이 숨었다(상세: docs/history).
# 코드펜스 미닫힘은 렌더가 깨져 저자가 알아채지만 HTML 주석은 렌더에 안 보여
# 아무 신호가 없다.
_AUTOGEN_START = re.compile(
    r"^\s*<!--\s*(?:" + "|".join(re.escape(s) for s, _ in _AUTOGEN_MARKERS) + ")"
)
_AUTOGEN_END = re.compile(
    r"^\s*<!--\s*(?:" + "|".join(re.escape(e) for _, e in _AUTOGEN_MARKERS) + ")"
)


def _authored_line_count(lines: list[str]) -> int:
    """자동생성 블록을 뺀 줄 수 — 저자가 실제로 쓴 몫만 센다.

    줄 길이는 이미 이 블록을 면제하는데 총량만 세면, 게이트가 저자에게 못 고칠
    것을 고치라고 요구하게 된다. 그 줄들은 gen_readmes가 각 문서 BLUF에서
    만들고, 그 BLUF는 원본 문서에서 이미 예산 대상이다 — 총량에 또 세면 같은
    텍스트를 두 번 규제하는 것이다.

    **YAML frontmatter는 반대로 총량에 그대로 센다**(길이·문장 규칙만 면제).
    자동생성 블록을 총량에서 빼는 근거는 "이미 원본에서 예산 대상"이라는
    이중계상인데, frontmatter는 어디서도 이중 계상되지 않는다. 저자가 못 고르는
    것은 값의 **줄바꿈**이지 필드 **개수**가 아니므로, 필드를 늘리면 총량이
    늘어나는 쪽이 맞다.
    """
    n = 0
    in_autogen = False
    for line in lines:
        if _AUTOGEN_START.search(line):
            in_autogen = True
            continue
        if _AUTOGEN_END.search(line):
            in_autogen = False
            continue
        if not in_autogen:
            n += 1
    return n


def _strip_review_refs(line: str, line_max: int | None) -> str:
    """검증 참조 스팬을 측정 대상에서 뺀다 — **그 스팬이 산문 예산 안일 때만**.

    면제의 취지는 "못 쪼개는 것"이었다(테스트 함수명은 줄바꿈하면 깨진다). 그런데
    길이 무제한 면제는 대괄호를 산문 우회 통로로 만들었다: 실측 다수가 산문 예산을
    넘었고, 긴 줄도 참조를 빼면 짧게 측정돼 통과했다.
    스팬 자체가 산문 한 줄 예산을 넘겼다면 그것은 더는 못 쪼개는 참조가 아니라
    대괄호에 들어간 산문이므로, 면제 자격을 잃고 그냥 산문으로 측정된다.

    **임계값은 새 매직넘버가 아니라 그 유형의 `line_max` 재사용이다** — 수치의
    정본은 폼이고(모듈 주석) 여기에 두 번째 수치를 박으면 언젠가 어긋난다.
    `line_max`가 없으면(폼이 산문 상한을 안 걸었으면) 면제를 거둘 잣대도 없으므로
    종전대로 전부 뺀다.

    면제를 잃은 스팬은 길이뿐 아니라 문장·좌표 규칙에도 노출된다 — 의도한 결과다.
    "산문이라 길이를 진다"면서 같은 텍스트를 문장 규칙에서만 빼주면 그게 다음
    우회로가 된다.
    """
    if line_max is None:
        return _REVIEW_REF.sub("", line)
    return _REVIEW_REF.sub(
        lambda m: "" if len(m.group(0)) <= line_max else m.group(0), line
    )


def _strip_link_urls(line: str) -> str:
    """마크다운 링크 `[라벨](URL)`에서 **URL(괄호부)만** 길이 측정에서 빼고 라벨은
    남긴다. `_strip_review_refs`와 나란한 관용구지만 스팬 전체가 아니라 URL만 지운다.

    왜 URL만인가 — URL은 안 쪼개지는 경로다(줄바꿈하면 링크가 깨진다), 표 행·코드펜스와
    같은 원리로 길이 면제. 라벨(대괄호부)은 산문이라 그대로 세, 라벨을 우회 통로로
    못 쓴다(_strip_review_refs가 대괄호를 산문 우회로로 열어줬던 실측 회귀와 같은 함정
    차단). `_REVIEW_REF`처럼 별도 상한을 두지 않는 이유: 긴 URL은 여전히 못 쪼개는
    경로라 면제가 타당하고, 상한을 두면 정당한 긴 파일경로가 도로 리젝된다.

    **공백 있는 괄호는 면제하지 않는다** — 진짜 URL/경로엔 공백이 없다(공백 URL은
    렌더가 깨진다). 괄호에 공백을 넣은 건 안 쪼개지는 경로가 아니라 괄호에 우겨넣은
    산문이므로 그냥 산문으로 측정한다(공짜 바이패스 차단). 문장 축은 별개다 —
    호출측이 이 함수를 **길이 측정 사본에만** 적용하고 문장·좌표 검사는 원본으로 잰다.
    """
    def _repl(m: re.Match) -> str:
        url = m.group(1)
        if any(c.isspace() for c in url):
            return m.group(0)  # 공백 URL = 못 쪼개는 경로 아님 → 면제 안 함
        return m.group(0)[: -(len(url) + 2)]  # 뒤 "(URL)" 제거, "[라벨]"만 남긴다
    return _LINK.sub(_repl, line)


def load_budgets(form_name: str) -> dict[str, int]:
    """폼 파일에서 예산을 뽑는다. 폼이 없으면 빈 dict.

    **빈 dict가 항상 실패는 아니다** — 유형 전용 폼이 없는 게 정상인 유형(예:
    guide)도 있어(폴백 설계) 이 함수 혼자서는 "문제냐 정상이냐"를 못 가른다.
    fail-closed 판단은 호출자 check_file()이 한다: 유형 폼+전역 폴백을 합쳐도
    예산을 하나도 못 뽑았을 때만(전역 폴백까지 실패) 리젝한다.
    """
    path = FORM_DIR / f"{form_name}.md"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for key, pat in _BUDGET_PATS.items():
        m = pat.search(text)
        if m:
            out[key] = int(m.group(1))
    return out


def doc_type(path: Path) -> str | None:
    """경로에서 유형을 판정한다. docs/<유형>/foo.md → <유형>."""
    parts = path.parts
    if len(parts) >= 2 and parts[0] == "docs":
        return parts[1]
    # 에이전트 정의(.claude/agents/*.md)는 docs/ 밑에 안 살아 위 갈래에 안 걸렸고,
    # 그래서 유형 없이 전역 폴백(rules 예산)으로 **우연히** 떨어졌다. 우연은 근거가
    # 아니라 다음에 rules 예산이 바뀌면 조용히 어긋난다 — 자기 폼(agent-def)에 건다.
    # **위 docs/ 갈래와 대칭으로 경로 맨 앞만 본다**(저장소 루트 상대). 중첩된
    # 다른 저장소의 `<하위 저장소>/.claude/agents/`까지 잡는 위치-무관 스캔은 활성
    # 사례가 0이라 유예한다: pre-commit은 언제나 자기 저장소 루트
    # (`git rev-parse --show-toplevel`) 기준으로만 --staged를 돌리고 — 하위 저장소는
    # 별개 저장소라 각자 훅이 각자 루트에서 돈다. 다른 저장소 트리가 중첩되는
    # 경로가 있어도 보통 .gitignore라 --staged가 못 보며, doc_type()/check_file()을
    # 그런 경로로 부르는 코드도 없다.
    # 실제 호출 경로가 생기면 그때 스캔으로 넓혀라 — 지금 넓히면 근거 없는 분기다.
    if len(parts) >= 3 and parts[:2] == _AGENT_DEF_DIR:
        return _AGENT_DEF_TYPE
    # 에이전트 설정 파일은 경로가 아니라 이름이 유형이다 — 루트에도 하위 저장소에도
    # 같은 이름으로 산다.
    if path.name in _AGENT_CONFIG_NAMES:
        return "agents"
    return None


def check_forbidden_refs(path: Path, lines: list[str]) -> list[str]:
    """금지 등재된 참조가 되살아났는지 본다.

    사람이 한 번 "이 참조는 불필요하다"고 판정한 쌍이 다시 들어오는 것만
    막는다 — 무엇이 필요한 참조인지는 기계가 모르고, 알 필요도 없다.
    """
    rel = path.as_posix()
    banned = [(src, dst) for src, dst in FORBIDDEN_REFS if src == rel]
    if not banned:
        return []

    violations: list[str] = []
    for i, line in enumerate(lines, 1):
        for target in _LINK.findall(line):
            for _, dst in banned:
                if dst in target:
                    violations.append(
                        f"{path}:{i}: 금지된 참조({dst}) — 불필요하다고 판정돼 "
                        f"FORBIDDEN_REFS에 등재된 참조다. 되살리려면 그 등재를 "
                        f"먼저 지워라."
                    )
    return violations


def check_file(path: Path) -> list[str]:
    """워킹트리 파일에 폼을 적용한다(직접 호출·감사용). 빈 리스트 = 통과."""
    if path.as_posix() in WHITELIST:
        return []
    return _check_content(path, path.read_text(encoding="utf-8"))


def _check_content(path: Path, text: str) -> list[str]:
    """주어진 콘텐츠 문자열에 폼을 적용한다 — 소스가 워킹트리든 인덱스 blob든.
    --staged는 인덱스 blob을 넘겨, 위반 줄번호가 staged diff의 added-set과 같은
    좌표계가 되게 한다(워킹트리·인덱스 갈림에 의한 fail-open을 구조적으로 차단)."""
    # split("\n")은 후행 개행이 있는(표준) 파일에서 팬텀 빈 줄을 하나 더 만들어
    # 실제 줄 수보다 항상 1 많게 센다(회귀: 실제 100줄 문서가 101줄로 오탐 리젝).
    lines = text.splitlines()
    kind = doc_type(path)

    # 유형 폼이 예산을 하나라도 선언했으면 그 폼만 정본이다 — 미선언 항목을
    # 전역 폴백으로 메우면 폼이 의도적으로 뺀 상한이 되살아난다(history 폼은
    # BLUF 상한을 안 건다고 명시하는데 rules의 100자가 끼어들어, 이미 커밋된
    # history 2건이 손대는 순간 리젝됐다). 폼과 어긋난 게이트는 꺼진다.
    budgets = load_budgets(kind) if kind else {}
    if not budgets:
        budgets = load_budgets(_GLOBAL_FORM)
    line_max = budgets.get("line_chars")
    bluf_max = budgets.get("bluf_chars")
    lines_max = budgets.get("max_lines")

    # 금지 참조는 예산과 무관한 축이라 예산 판정 전에 모은다.
    violations: list[str] = check_forbidden_refs(path, lines)

    # fail-closed: 전역 폴백(_GLOBAL_FORM)조차 예산을 하나도 못 뽑았으면(폼
    # 디렉터리 없음·파일 없음·파싱 실패 등) line_max·bluf_max·lines_max가 전부
    # None이 된다. 이 상태로 조용히 통과시키면 "위반이 없어서 통과"가 아니라
    # "잴 자가 없어서 통과"가 되어 게이트가 무력화된다 — 검사기 자체의 부재
    # (훅 래퍼가 fail-open으로 처리하는 층)와는 다른 층의 문제이므로 여기서는
    # 반대로 fail-closed로 리젝한다.
    if line_max is None and bluf_max is None and lines_max is None:
        form_path = FORM_DIR / f"{_GLOBAL_FORM}.md"
        reason = "폼 파일 없음" if not form_path.is_file() else "폼은 있으나 예산 파싱 실패"
        return violations + [
            f"{path}: 예산을 하나도 못 뽑음({reason}: {form_path}) — 위반이 없어서 "
            f"통과가 아니라 잴 자가 없어서 통과할 뻔한 것이다. 폼 파일·문구를 "
            f"확인하라(fail-closed)."
        ]

    authored = _authored_line_count(lines)
    if lines_max and authored > lines_max:
        _via = f"{RULE_DOC_AUTHORING} 제3조로 " if RULE_DOC_AUTHORING else ""
        violations.append(
            f"{path}: {authored}줄 > {lines_max}줄 — 문서가 비대하다"
            f"{_rule_cite(RULE_DOC_AUTHORING, '비대 상한')}. 먼저 {_via}"
            f"기계-사실 재서술을 쳐내라([✅test]·개수·좌표를 링크·이름참조로). "
            f"그래도 넘으면 쪼개거나 docs/history로 내려라."
        )

    in_fence = False
    in_autogen = False
    in_comment = False
    # YAML frontmatter는 저자가 형식을 못 고르는 영역이라 면제한다 — 스칼라 값에
    # 줄바꿈을 넣을 수 없으므로 "한 줄 한 문장"·길이 상한을 물리적으로 지킬 수
    # 없다(에이전트 정의 .claude/agents/*.md의 description·tools가 그 자리다).
    # **여는 자리는 파일 첫 줄로 못 박는다** — 본문 어디서나 열게 두면 수평선
    # `---` 하나가 나머지 문서 전체의 게이트를 끈다(자동생성 마커 부분일치로
    # 위반이 숨었던 실사고와 같은 부류).
    in_frontmatter = bool(lines) and lines[0].strip() == "---"
    for i, line in enumerate(lines, 1):
        if in_frontmatter:
            if i > 1 and line.strip() == "---":
                in_frontmatter = False
            continue
        if _AUTOGEN_START.search(line):
            in_autogen = True
            continue
        if _AUTOGEN_END.search(line):
            in_autogen = False
            continue
        # HTML 주석 블록은 렌더 안 되는 저자 안내(폼 힌트·corpus-exclude 마커)라
        # 예산·문장 규칙에서 면제한다 — 코드 주석에 "한 문장" 강제하지 않는 것과
        # 같다. autogen(BLUF-INDEX)을 먼저 걸러 이 로직이 그 블록을 안 삼킨다.
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if "<!--" in line:
            if "-->" not in line:
                in_comment = True
            continue
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        # 표 행·코드펜스·자동생성 블록은 면제 — 앞의 둘은 쪼개면 깨지고,
        # 뒤는 저자가 손댈 수 없다. 못 쓰는 게이트는 꺼진다.
        if in_fence or in_autogen or _TABLE_ROW.match(line):
            continue

        # BLUF 줄은 BLUF 예산으로만 잰다. 산문 상한으로 또 재면 폼이 허용한
        # 길이를 쓸 수 없고(rules는 BLUF 100자 > 산문 80자), 상한을 안 건
        # 유형의 BLUF가 산문 상한으로 떨어진다.
        if _BLUF.match(line):
            body = _BLUF.sub("", line)
            if bluf_max and len(body) > bluf_max:
                violations.append(
                    f"{path}:{i}: BLUF {len(body)}자 > {bluf_max}자 — "
                    f"요약 자리에 문단을 넣지 마라."
                )
            continue

        # 검증 참조 스팬은 길이에서 뺀다 — 함수명이라 못 쪼갠다. 남은 산문은
        # 여전히 상한을 진다(참조만 길고 서술은 짧으면 통과, 서술이 길면 리젝).
        # 스팬 자체가 line_max를 넘으면 면제가 걷힌다(`_strip_review_refs`).
        measured = _strip_review_refs(line, line_max)
        # 한 줄에 문장이 여럿이면 리젝 — 길이(80자)와 별개 축이다. 길이는
        # 프록시라 접기로 우회되지만, 이건 "한 줄 = 한 문장" 구조를 직접 건다.
        if not _HEADING.match(line) and _SENTENCE_END.search(measured):
            _reason5 = f", {RULE_DOC_AUTHORING} 제5조" if RULE_DOC_AUTHORING else ""
            violations.append(
                f"{path}:{i}: 한 줄에 문장이 여럿이다 — 문장마다 줄바꿈해 불릿로 "
                f"빼라(단문이 읽힌다{_reason5})."
            )
        # 길이 축에서만 링크 URL(안 쪼개지는 경로)을 마저 벗긴다 — 별도 사본이라
        # 문장·좌표 검사(measured)엔 영향 없다(면제는 길이 축 한정, `_strip_link_urls`).
        length_measured = _strip_link_urls(measured)
        if line_max and len(length_measured) > line_max:
            _reason5 = f", {RULE_DOC_AUTHORING} 제5조" if RULE_DOC_AUTHORING else ""
            violations.append(
                f"{path}:{i}: {len(length_measured)}자 > {line_max}자 — 흐름을 우겨넣지 "
                f"말고 쪼개라(상한은 채울 칸이 아니다{_reason5})."
            )
        if kind not in _COORD_EXEMPT_TYPES:
            for coord in _COORD.findall(measured):
                cite3 = _rule_cite(RULE_DOC_AUTHORING, "제3조")
                violations.append(
                    f"{path}:{i}: 손으로 친 줄번호 좌표({coord}) — 편집마다 밀려 "
                    f"stale된다{cite3}. 심볼명이나 SHA-고정 경로를 써라."
                )

    return violations


def staged_files() -> list[tuple[Path, Path | None]]:
    """스테이징된 .md를 (신규경로, 옛경로|None)로 반환한다. 개명이면 옛경로가
    채워진다.

    개명(R)을 필터에서 빼면 개명+편집을 한 커밋에 하는 것만으로 게이트 전체
    (좌표·줄예산·문장 등)가 통째로 우회된다(적대검증 지적). 개명은 옛/새 경로를
    둘 다 알아야 rename-aware 부분 diff를 뜰 수 있어 옛경로도 함께 반환한다."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=False,
    ).stdout
    result: list[tuple[Path, Path | None]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) >= 3:
            old, new = parts[1], parts[2]
            if new.endswith(".md") and Path(new).is_file():
                result.append((Path(new), Path(old)))
        elif len(parts) >= 2:
            new = parts[1]
            if new.endswith(".md") and Path(new).is_file():
                result.append((Path(new), None))
    return result


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def _staged_hunk_lines(path: Path, old_path: Path | None = None):
    """스테이징 diff를 한 번만 파싱해 헌크 콘텐츠 줄을 (kind, new_ln, content)로 낸다.

    - kind: `"+"`(추가) 또는 `"-"`(삭제).
    - new_ln: 추가줄의 신규-파일 줄번호(삭제줄은 직전 값 — 소비자가 무시).
    - content: 선두 +/- 마커 1자를 뗀 줄 내용.

    헤더(`--- a/`·`+++ b/`·rename)와 콘텐츠(`-`/`+`)를 접두어로 가르면 삭제 내용이
    `---`(수평선)면 `----`가 돼 오분류된다 — 진짜 구분은 첫 `@@` 전/후 '위치'다.
    개명이면 옛/새 경로를 둘 다 줘야 git이 rename 짝을 찾아 부분 diff를 뜬다(새
    경로만 주면 전체를 신규파일로 봐 캐스케이드가 부활한다).

    staged_line_delta(줄 세기)·staged_char_delta(문자 세기)가 이 한 파서를 공유한다
    — 서브프로세스 호출·정규식·위치 상태머신을 두 벌 복붙하던 걸 한 곳으로 모은다."""
    cmd = ["git", "diff", "--cached", "-M", "-U0", "--no-color", "--"]
    cmd += [old_path.as_posix(), path.as_posix()] if old_path else [path.as_posix()]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout
    new_ln = 0
    in_hunk = False
    for line in out.splitlines():
        h = _HUNK.match(line)
        if h:
            new_ln = int(h.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            yield "+", new_ln, line[1:]
            new_ln += 1
        elif line.startswith("-"):
            yield "-", new_ln, line[1:]


def staged_line_delta(path: Path, old_path: Path | None = None) -> tuple[set[int], int]:
    """스테이징 diff의 (추가된 신규-파일 줄번호 집합, 삭제 줄 수)를 판정한다.

    이 줄들만 폼을 강제하고 안 건드린 기존 줄은 유예한다 — 진행형의 진짜 뜻은
    '손댄 문서 전체'가 아니라 '손댄 줄'이다(한 줄 고치려 문서 전체를 재정합
    강요하던 캐스케이드를 끊는다). 새 파일은 모든 줄이 추가로 잡혀 전량 검사된다.
    파싱(헤더/콘텐츠 위치 판정·rename 부분 diff)은 `_staged_hunk_lines`가 담당한다."""
    added: set[int] = set()
    removed = 0
    for kind, new_ln, _content in _staged_hunk_lines(path, old_path):
        if kind == "+":
            added.add(new_ln)
        else:
            removed += 1
    return added, removed


def staged_char_delta(path: Path, old_path: Path | None = None) -> int:
    """스테이징 diff의 순증 문자 수(추가 문자 수 - 삭제 문자 수, 줄바꿈 제외)를
    판정한다. `staged_line_delta`와 같은 파서(`_staged_hunk_lines`)를 쓰되 줄이
    아니라 각 줄의 콘텐츠 길이(선두 +/- 마커 제외)를 합산한다.

    **왜 문자냐** — 줄 수는 포맷의 함수다: 산문 한 줄에 흐름을 우겨넣지 말라는
    규칙(줄당 한 문장)을 지키려 긴 줄을 문장마다 쪼개면, 내용은 그대로인데
    줄만 는다. 문자 수는 내용의 함수다: 쪼개도 늘어나는 건 개행·불릿 마커 몇
    자뿐이다. 총량("문서가 비대하다") 판정을 줄 순증으로 재면, 한 규칙(문장당
    줄바꿈)을 지킨 사람이 다른 규칙(총량 상한)의 위반을 뒤집어쓴다 — 두
    규칙이 서로를 배반한다. 문자 순증으로 재야 이 자기모순이 풀린다.
    """
    added_chars = 0
    removed_chars = 0
    for kind, _new_ln, content in _staged_hunk_lines(path, old_path):
        if kind == "+":
            added_chars += len(content)
        else:
            removed_chars += len(content)
    return added_chars - removed_chars


def _staged_blob(path: Path) -> str:
    """인덱스(스테이징)에 있는 그 파일의 blob 텍스트 — 커밋될 실제 내용이다.

    워킹트리(`path.read_text`)가 아니라 이걸 검사해야 staged diff의 added-set과
    같은 콘텐츠·좌표계가 된다. 안 그러면 add 후 재편집·부분 스테이징으로 둘이
    갈라져 위반이 엉뚱한 줄번호로 계산돼 조용히 버려진다(fail-open). 이 repo의
    watermark.py::read_committed_text가 같은 병을 이미 이 방식으로 고쳤다. 인덱스에
    없으면(비정상) 워킹트리로 폴백한다."""
    out = subprocess.run(
        ["git", "show", f":{path.as_posix()}"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout if out.returncode == 0 else path.read_text(encoding="utf-8")


def check_staged(path: Path, old_path: Path | None = None) -> list[str]:
    """스테이징된 blob(커밋될 내용)의 위반 중 이번 diff가 추가/변경한 줄에 걸린
    것만 남긴다.

    문서 전체 줄수 초과는 이번 변경이 **문자** 순증(추가 문자>삭제 문자)일
    때만 보고한다 — 안 건드린 비대함까지 커밋자에게 떠넘기지 않는다. **줄
    순증이 아니라 문자 순증**을 보는 이유: 줄 수는 포맷의 함수라 긴 줄을
    문장마다 쪼개면(줄당 한 문장 규칙 준수) 내용은 그대로인데 줄만 늘어
    총량 위반이 되살아난다 — 두 규칙이 서로를 배반한다. 문자 수는 내용의
    함수라 쪼개도 개행·불릿 마커 몇 자뿐이다(`staged_char_delta` 참고). 예산
    파싱 실패 같은 구조적 위반은 줄과 무관하므로 항상 유지한다(게이트 무력화
    방지).

    **대가(정직 표기)**: 문자가 안 늘면 절대 줄수가 상한을 넘겨도 이 경로는
    보고하지 않는다. 재포맷만으로 새로 상한을 넘기는 케이스가 안 잡힌다는
    뜻이다. 전량 검사(`check_file`)가 그 백스톱인데 훅·CI 어디에도 안 걸려
    있다 — pre-commit은 `--staged`만 부른다. "N줄 상한"은 그래서 무조건이
    아니라 **문자가 늘 때만 걸리는 조건부**다."""
    if path.as_posix() in WHITELIST:
        return []
    all_v = _check_content(path, _staged_blob(path))
    if not all_v:
        return []
    added, _removed_lines = staged_line_delta(path, old_path)
    char_delta = staged_char_delta(path, old_path)
    per_line = re.compile(rf"^{re.escape(str(path))}:(\d+):")
    kept: list[str] = []
    for v in all_v:
        m = per_line.match(v)
        if m:
            if int(m.group(1)) in added:
                kept.append(v)
        elif "줄 — 문서가 비대하다" in v:
            if char_delta > 0:
                kept.append(v)
        else:
            kept.append(v)
    return kept


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    violations: list[str] = []
    if "--staged" in args:
        for new, old in staged_files():
            violations.extend(check_staged(new, old))
    else:
        for path in [Path(a) for a in args if not a.startswith("-")]:
            if path.is_file() and path.suffix == ".md":
                violations.extend(check_file(path))

    if not violations:
        return 0

    print(
        f"[check_doc_form] 문서 폼 리젝 — 위반 {len(violations)}건:",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    _via = f"{RULE_DOC_AUTHORING} 제3조로 " if RULE_DOC_AUTHORING else ""
    print(
        f"\n먼저 {_via}기계-사실 재서술을 쳐내라([✅test]·개수·좌표를"
        f"\n링크·이름참조로 — 이게 근본). 그다음 긴 줄은 불릿로 쪼개고, 그래도"
        f"\n상한을 넘으면 근거를 docs/history로 내려 \"## 관련\"에서 링크하라(최후)."
        f"\n예산·면제의 정본: {FORM_DIR}/<유형>.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
