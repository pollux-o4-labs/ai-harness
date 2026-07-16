# ai-harness

레포 공용 **문서·PR 게이트 일습**(pre-commit + PR 훅). `claude -p`나 vgo 없이 도는
**stdlib only** 파이썬이라, 어느 레포에 clone/복사해도 바로 붙는다. 게이트 설계·
근거는 vgo(vector-graph-ontology)에서 뽑아왔고, 여기 실린 설정값은 그 실사용 예다.

## 무엇이 들었나

| 파일 | 역할 |
|---|---|
| `scripts/check_doc_form.py` | 문서 폼 게이트 — 줄수·산문 80자·한 줄 한 문장·BLUF·좌표(줄번호) 금지. `--staged`는 **diff 스코프**(손댄 줄만). |
| `scripts/check_pr_body.py` | PR 본문 게이트 — 필수 섹션·섹션별 분량·내부 은어 풀이·확인 체크리스트. `--hook`으로 `gh pr create`/`gh pr merge` 리젝. |
| `scripts/gen_readmes.py` | 폴더 README의 BLUF-INDEX 자동생성 + drift 검사(`--check`). |
| `scripts/install_hooks.py` | `hooks/`를 `.git/hooks/`로 설치. |
| `hooks/pre-commit` | 커밋 전 `check_doc_form --staged` + `gen_readmes --check`. |
| `.claude/settings.json` | `check_pr_body`를 Claude Code PreToolUse 훅으로 배선. |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 본문 골격(4섹션 + 확인 체크리스트). |
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

## repo별 특화 지점

공용 스크립트는 그대로 쓰고, 아래만 대상 레포에 맞춘다:

- `docs/docs-format/*.md` — 유형·예산. 새 문서 유형을 쓰면 `<유형>.md`를 추가하고
  `줄수 · 산문 한 줄 N자 · BLUF 한 줄 N자` 문구로 상한을 적는다(스크립트가 파싱).
- `scripts/check_pr_body.py`의 `JARGON_TERMS` — 풀이를 강제할 내부 은어. **여기
  실린 목록은 vgo 예시**라 대상 레포 은어로 갈아야 한다(상습범만 등재).
- `REQUIRED_CHECKS`·`SECTION_BUDGETS` — 확인 항목·섹션 분량.
- `.github/PULL_REQUEST_TEMPLATE.md` — 위 `REQUIRED_CHECKS`와 문구가 **정확히**
  일치해야 한다(한 글자만 달라도 전 PR 리젝).

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
