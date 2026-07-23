> **BLUF:** ai-harness를 저장소에 설치하고 저장소별 설정을 맞추는 절차.

## 설치

머신에 한 번 설치하면 어느 저장소에서든 `ai-harness` 명령을 쓴다.

```bash
uv tool install git+https://github.com/pollux-o4-labs/ai-harness.git
```

## 저장소에 걸기

1. 대상 저장소 루트에 `gate_config.py`를 만든다(아래 값 참고).
2. `ai-harness install-hooks`로 pre-commit 훅을 설치한다.
3. (선택) AI 세션의 PR 게이트까지 걸려면 `.claude/settings.json`에
   `ai-harness check-pr --hook`을 부르는 PreToolUse 훅을 둔다.

## 게이트 목록

| 명령 | 역할 |
|---|---|
| `check-pr` | PR 본문 게이트. `--hook`은 `gh pr create`·`gh pr merge`를 거부한다. |
| `check-doc` | 문서 폼 게이트. `--staged`는 손댄 줄만 검사한다(diff 스코프). |
| `gen-readmes` | 폴더 README BLUF 인덱스 자동생성. `--check`는 drift만 본다. |
| `install-hooks` | `hooks/`를 `.git/hooks/`로 설치한다. |

CLI가 PATH에 없으면 훅은 fail-open으로 건너뛴다(저장소 자체 잠금 방지).

리뷰 종합 코멘트(`gh pr comment`)는 골격도 강제한다.
`## 리뷰 종합` 헤더를 단 코멘트는 필수 `##` 섹션과 등급 라벨을 갖춰야 한다.
필수 섹션·라벨은 `docs_format/pr-comment.md`가 정본이라 그 파일만 바꿔 조정한다.
게이트는 형식(있나)만 보고, 등급의 진실성은 리뷰어가 판단한다.

## gate_config.py 값

core는 그대로 두고 이 파일만 저장소에 맞춘다.
각 값의 상세 설명은 그 파일 주석에 있으므로 여기서 재서술하지 않는다.

- `DISABLED_GATES` — 이 저장소에서 끌 게이트(기본은 빈 튜플, 전부 켬).
- `JARGON_TERMS` — 풀이를 강제할 내부 용어(기본값은 빈 목록).
- `EXEMPT_SECTIONS`·`build_exempt_shape()` — 조직 PR 템플릿의 골격 섹션.
- `RULE_*` — 리젝 메시지가 인용할 규칙 조문(규칙 문서가 없으면 공란).

문서 유형별 예산은 core에 번들된 `docs_format/*.md`가 정본이다.
`.github/PULL_REQUEST_TEMPLATE.md`는 core의 섹션명과 맞아야 한다.

## 정본 방향

게이트 로직(core)의 정본은 이 저장소 하나다.
설치본은 패키지를 그대로 쓰고, 각 저장소는 `gate_config.py`만 소유한다.
개선(새 검사·버그 수정)은 이 저장소에 반영하고, 각 저장소는 새 버전을 설치한다.
