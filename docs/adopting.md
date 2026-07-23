> **BLUF:** ai-harness를 다른 저장소에 채택하고 정본과 동기화하는 방법.

## 채택 절차

1. core 스크립트와 `gate_config.py`를 대상 저장소에 복사한다(또는 이 repo를 clone).
2. `python3 scripts/install_hooks.py`로 pre-commit 훅을 설치한다.
3. `gate_config.py`를 대상 저장소에 맞게 편집한다(아래).
4. (선택) AI 세션에서 PR 게이트까지 강제하려면 `.claude/settings.json` 훅을 둔다.

## 게이트 스크립트

| 스크립트 | 역할 |
|---|---|
| `check_doc_form.py` | 문서 폼 게이트. `--staged`는 손댄 줄만 검사한다(diff 스코프). |
| `check_pr_body.py` | PR 본문 게이트. `--hook`으로 `gh pr create`/`gh pr merge`를 거부한다. |
| `gen_readmes.py` | 폴더 README의 BLUF 인덱스를 자동생성하고 `--check`로 drift를 검사한다. |
| `check_gate_drift.py` | core가 저장소 간 바이트 동일한지 감시한다. |
| `gate_config.py` | 저장소별 설정 — 이 파일만 저장소마다 다르다. |
| `install_hooks.py` | `hooks/`를 `.git/hooks/`로 설치한다. |

## 무엇을 맞추나

core는 그대로 두고 `gate_config.py`만 편집한다.
각 값의 상세 설명은 그 파일 주석에 있으므로 여기서 재서술하지 않는다:

- `JARGON_TERMS` — 풀이를 강제할 내부 용어(기본값은 빈 목록).
- `EXEMPT_SECTIONS`·`build_exempt_shape()` — 조직 PR 템플릿의 골격 섹션.
- `RULE_*` — 리젝 메시지가 인용할 규칙 조문(규칙 문서가 없으면 공란).

문서 유형별 예산은 `docs/docs-format/*.md`에서 정한다.
`.github/PULL_REQUEST_TEMPLATE.md`는 core의 `REQUIRED_CHECKS`와 문구가 일치해야 한다.
`REQUIRED_CHECKS`·`SECTION_BUDGETS`는 core 공유값이며 저장소별 오버라이드 대상이 아니다.

## 동기화 방향

정본은 이 저장소이다.
개선(새 검사·버그 수정)은 이곳에 먼저 반영하고, 각 저장소는 core를 복사해 사용한다.
저장소에서 급히 고친 개선은 되돌려 정본에도 반영해야 한다.
core가 사본마다 갈라졌는지는 `check_gate_drift.py`가 감시한다.
형제 저장소 경로를 환경변수 `GATE_CANONICAL_DIR`로 주면 core를 바이트 비교한다.
