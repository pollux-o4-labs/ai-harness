# ai-harness

레포 공용 **문서·PR 게이트 일습**(pre-commit + PR 훅). `claude -p`나 vgo 없이 도는
**stdlib only** 파이썬이라, 어느 레포에 clone/복사해도 바로 붙는다. 게이트 설계·
근거는 vgo(vector-graph-ontology)에서 뽑아왔고, 여기 실린 설정값은 그 실사용 예다.

## 무엇이 들었나

| 파일 | 역할 |
|---|---|
| `scripts/check_doc_form.py` | 문서 폼 게이트 — 줄수·산문 80자·한 줄 한 문장·BLUF·좌표(줄번호) 금지. `--staged`는 **diff 스코프**(손댄 줄만). |
| `scripts/check_pr_body.py` | PR 본문 게이트 — 필수 섹션·섹션별 분량·**예산 없는 섹션의 형태**·내부 은어 풀이·확인 체크리스트. `--hook`으로 `gh pr create`/`gh pr merge` 리젝. |
| `scripts/gen_readmes.py` | 폴더 README의 BLUF-INDEX 자동생성 + drift 검사(`--check`). |
| `scripts/gate_config.py` | **repo별 특화 지점**(아래 절) — 은어 목록·면제 섹션·규칙 인용. 이 파일만 레포마다 다르다. |
| `scripts/check_gate_drift.py` | core 파일이 형제 저장소 정본과 바이트 동일한지 비교(`GATE_CANONICAL_DIR` 환경변수, 없으면 skip) + 특정 저장소 지시 서술 잔존 검사. |
| `scripts/install_hooks.py` | `hooks/`를 `.git/hooks/`로 설치. |
| `hooks/pre-commit` | 커밋 전 `check_doc_form --staged` + `gen_readmes --check`. |
| `.claude/settings.json` | `check_pr_body`를 Claude Code PreToolUse 훅으로 배선. |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 본문 골격. 조직 공용 폼과 게이트 폼의 통합본 — 섹션 목록의 정본은 `check_pr_body.py`다. |
| `docs/docs-format/*.md` | 유형별 **예산 폼**(줄수·80자·BLUF 상한). check_doc_form이 파싱하는 정본. |

## 설치

```bash
# 1) 이 레포를 clone하거나 위 파일들을 대상 레포에 복사
# 2) pre-commit 훅 설치
python3 scripts/install_hooks.py
# 3) (선택) check_pr_body를 Claude Code 세션에서 강제하려면
#    .claude/settings.json의 PreToolUse 훅을 대상 레포에 둔다
```

- 게이트는 검사기 파일이 없으면 조용히 통과한다(fail-open) — 파일 부재로 레포
  전체가 잠기지 않게. 반대로 폼 예산을 하나도 못 뽑으면 리젝한다(fail-closed).
- `scripts/gate_config.py`는 core와 **반드시 같이** 복사한다 — 없으면 core가
  이 파일을 import하다 `ModuleNotFoundError`로 죽는다.

## repo별 특화 지점

공용 스크립트(core: `check_pr_body.py`·`check_doc_form.py`·`gen_readmes.py`·
`check_gate_drift.py`)는 그대로 쓴다.
**`scripts/gate_config.py`만** 대상 레포에 맞춘다.
core 파일 자체를 고치면 그 순간부터 정본과 갈라진다(`check_gate_drift.py`가
core만 바이트 비교하고 `gate_config.py`는 뺀다).

- `JARGON_TERMS` — 풀이를 강제할 내부 은어.
  **여기 실린 목록은 vgo 예시**라 대상 레포 은어로 갈아야 한다(상습범만 등재).
- `EXEMPT_SECTIONS`·`build_exempt_shape()` — 조직 공용 폼에서 온 골격 섹션
  (글자 예산 대신 **형태**로 강제).
  org마다 골격이 다르므로 대상 조직 템플릿에 맞춘다.
  새 면제 섹션을 늘리면 `build_exempt_shape()`에 허용 형태도 **반드시 같이**
  정해야 한다 — 형태 없는 면제 섹션은 곧 예산 회피구다(산문을 거기 옮기면
  예산이 무력화된다).
- `RULE_DOC_AUTHORING`·`RULE_REVIEW_EVIDENCE` — core 리젝 메시지가 인용할
  규칙 조문.
  규칙 문서(`docs/rules/*`)가 있는 레포만 채운다 — 없으면 공란으로 둬서 core가
  죽은 인용을 안 달게 한다.
- `docs/docs-format/*.md` — 유형·예산.
  새 문서 유형을 쓰면 `<유형>.md`를 추가하고 `줄수 · 산문 한 줄 N자 · BLUF
  한 줄 N자` 문구로 상한을 적는다(스크립트가 파싱).
- `.github/PULL_REQUEST_TEMPLATE.md` — core의 `REQUIRED_CHECKS`와 문구가
  **정확히** 일치해야 한다(한 글자만 달라도 전 PR 리젝).
  `tests/test_check_pr_body.py`가 이 정합을 파일 대조로 강제한다.

`REQUIRED_CHECKS`·`SECTION_BUDGETS`는 이제 **core 공유값**이다 — repo별
오버라이드 대상이 아니다.
이 값이 레포마다 다르면 그 자체가 판정 기준의 갈라짐이므로, 다른 값이
필요하면 core에서 값을 맞추는 쪽으로 수렴시킨다.

## 동기화 방향 (정본·재발 방지)

이 저장소가 게이트 로직의 **정본**이다.
개선(새 검사·버그 수정)은 여기 먼저 착지하고, 각 repo는 core 파일을 복사한 뒤
위 "repo별 특화 지점"대로 `gate_config.py`만 오버라이드한다.

- repo에서 급히 고친 개선은 되돌려 이 정본에도 반영해야 한다.
  안 하면 정본이 뒤처지고 사본마다 갈라진다(vgo·ai-harness가 양방향으로 갈라진 이력).
- core가 사본마다 달라졌는지는 `scripts/check_gate_drift.py`로 잡는다 — 형제
  저장소 경로를 환경변수 `GATE_CANONICAL_DIR`로 주면 core 파일(`gate_config.py`는
  제외)을 바이트 비교하고, 경로가 없으면 그 비교만 skip한다(특정 저장소를
  가리키는 서술이 core에 남았는지는 경로 유무와 무관하게 항상 본다).

## 검증

```bash
pytest            # 게이트 스크립트 자기검증(무DB·무LLM·stdlib)
```

## 설계 원칙 (왜 이 형태인가)

- **코드 강제 > 자기보고**: 측정 가능한 성질을 재 exit code로 막는다. 체크리스트는
  정직한 자기신고로만 표기(글자 x일 뿐 참거짓 증거 아님) — 저자가 한 번 짚게 한다.
- **재서술 금지**: 예산 수치는 폼에만 두고 어디서도 재서술하지 않는다(갈라짐 방지).
- **diff 스코프**: `--staged`는 손댄 줄만 강제 — 밀집 비정합 문서에 한 줄 고치려
  전체 재정합을 강요하지 않는다(커밋될 인덱스 내용 기준).
