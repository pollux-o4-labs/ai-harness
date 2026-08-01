> **BLUF:** ai-harness를 저장소에 설치하고 저장소별 설정을 맞추는 절차.

## 설치

머신에 한 번 설치하면 어느 저장소에서든 `ai-harness` 명령을 쓴다.

```bash
uv tool install git+https://github.com/pollux-o4-labs/ai-harness.git
```

## 저장소에 걸기

1. 대상 저장소 루트에 `gate_config.py`를 만든다(아래 값 참고).
2. `ai-harness install-hooks`로 pre-commit 훅을 설치한다.
3. `gen-readmes --check`(스코프 없는 전체 스캔)를 pre-commit과 별도 지점에 배선한다.
   - pre-commit의 `gen-readmes --check --staged`는 이번 커밋이 바꿀 수 있는 폴더로만 좁혀서 본다.
   - 손대지 않은 폴더의 선행 어긋남은 그 경로로 안 잡힌다.
   - 출하 검사·CI·주기 실행 등 이 저장소가 가진 지점에 전체 스캔을 걸어야 그 어긋남이 잡힌다.
   - ai-harness는 이 배선을 대신 걸어주지 않는다 — 안 걸면 어긋남이 계속 방치된다.
4. (선택) AI 세션의 PR 게이트까지 걸려면 `.claude/settings.json`에
   `ai-harness check-pr --hook`을 부르는 PreToolUse 훅을 둔다.

## 게이트 목록

| 명령 | 역할 |
|---|---|
| `check-pr` | PR 본문 게이트. `--hook`은 `gh pr create`·`gh pr merge`를 거부한다. |
| `check-doc` | 문서 폼 게이트. `--staged`는 손댄 줄만 검사한다(diff 스코프). |
| `gen-readmes` | 폴더 README BLUF 인덱스 자동생성. `--check`는 drift만 본다. |
| `gen-pr-template` | `.github/PULL_REQUEST_TEMPLATE.md`를 `REQUIRED_CHECKS` 등에서 생성. `--check`는 drift만 본다. |
| `install-hooks` | `hooks/`를 `.git/hooks/`로 설치한다. |
| `install-agents` | 리뷰어 템플릿을 `.claude/agents/`로 설치한다(기존 손질은 보존). 채울 자리는 실행 출력이 안내한다. |
| `install-rules` | 공용 규칙 조문을 `.claude/rules/`로 설치한다(정본이라 덮는다). |
| `relink-docs` | 토픽 폴더 재편 때 마크다운 링크를 재작성한다. `--check`는 깨진 링크만 스캔한다. |

CLI가 PATH에 없으면 훅은 fail-open으로 건너뛴다(저장소 자체 잠금 방지).

리뷰 종합 코멘트(`gh pr comment`)는 골격도 강제한다.
`## 리뷰 종합` 헤더를 단 코멘트는 필수 `##` 섹션과 등급 라벨을 갖춰야 한다.
필수 섹션·라벨은 core 번들 `docs_format/pr-comment.md`가 정본이다(전 레포 공통).
게이트는 형식(있나)만 보고, 등급의 진실성은 리뷰어가 판단한다.

## gate_config.py 값

core는 그대로 두고 이 파일만 저장소에 맞춘다.
각 값의 상세 설명은 그 파일 주석에 있으므로 여기서 재서술하지 않는다.

- `DISABLED_GATES` — 이 저장소에서 끌 게이트(기본은 빈 튜플, 전부 켬).
- `EXTRA_AUTOGEN_MARKERS` — 저장소 자체 splice 도구의 마커 쌍을 core 마커에 보탠다(기본은 빈 튜플).
- `EXTRA_WHITELIST` — check-doc 줄 예산을 면제할 저장소별 문서 경로(기본은 빈 집합).
- `EXEMPT_SECTIONS`·`build_exempt_shape()` — 조직 PR 템플릿의 골격 섹션.
- `RULE_*` — 리젝 메시지가 인용할 규칙 조문(규칙 문서가 없으면 공란).

문서 유형별 예산은 core에 번들된 `docs_format/*.md`가 정본이다.
`.github/PULL_REQUEST_TEMPLATE.md`는 `gen-pr-template`가 core 상수에서 생성한다(손수정 금지).

## 정본 방향

게이트 로직(core)의 정본은 이 저장소 하나다.
설치본은 패키지를 그대로 쓰고, 각 저장소는 `gate_config.py`만 소유한다.
개선(새 검사·버그 수정)은 이 저장소에 반영하고, 각 저장소는 새 버전을 설치한다.
