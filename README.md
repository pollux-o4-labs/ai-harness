# ai-harness

> **BLUF:** 말 안 듣는 AI를 위한 문서·PR 게이트 — 설치형 CLI로 여러 저장소에 건다.

`stdlib`만 쓰는 파이썬이라 DB나 LLM 없이 동작한다.
검사기는 순수 룰(LLM 0)이라 결정적이다.

## 왜

AI 에이전트는(사람도) "문서를 참고하라" 같은 언어 지시를 잘 따르지 않는다.
그래서 ai-harness는 지시가 아니라 구조(exit code)로 강제한다.
규약(문서 폼·PR 형식)을 위반하면 커밋과 PR이 막힌다.

## 무엇을 막나

커밋·PR이 규약을 위반하면 훅이 이를 거부한다.

```text
$ git commit -m "docs 갱신"
[check-doc] 문서 폼 리젝 — 위반 1건:
  - docs/guide.md:12: 148자 > 80자 — 흐름을 우겨넣지 말고 쪼개라.
```

- **문서 폼** — 줄수·산문 80자·한 줄 한 문장·BLUF 상한.
- **PR 본문** — 필수 섹션·섹션별 분량·내부 용어 풀이·확인 체크리스트.
- **README 인덱스** — 폴더 BLUF 롤업 자동생성 + drift 검사.

## 설치

머신에 한 번 설치하면 `ai-harness` 명령이 PATH에 오른다.
저장소마다 스크립트를 복사하지 않는다.

```bash
uv tool install git+https://github.com/pollux-o4-labs/ai-harness.git
```

## 사용

```bash
ai-harness check-pr       # PR 본문 구조·분량 게이트
ai-harness check-doc      # 문서 폼(줄 예산) 게이트
ai-harness gen-readmes    # BLUF 기반 README 자동 생성
ai-harness install-hooks  # pre-commit 훅 설치
```

## 저장소별 설정

대상 저장소 루트에 `gate_config.py` 하나를 두면 그 값이 core를 덮는다.
없으면 번들 기본값(빈 은어 목록 등)으로 동작한다.
기본은 전 게이트 켬이고, 안 맞는 저장소만 `DISABLED_GATES`로 그 게이트를 끈다.
각 값의 의미는 `gate_config.py` 주석이 정본이다.

채택 절차·게이트 목록은 [docs/adopting.md](docs/adopting.md)에 있다.

## 검증

```bash
uv run pytest    # 게이트 자기검증(무DB·무LLM·stdlib)
```
