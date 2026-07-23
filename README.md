# ai-harness

> 말 안 듣는 AI를 위한 문서·PR 게이트.
> "문서를 참고하라"는 언어 지시로 해결되지 않는 것을 구조(exit code)로 강제한다.

`stdlib`만 사용하는 파이썬이므로 DB나 LLM 없이 어느 저장소에서나 사용할 수 있다.

## 왜

AI 에이전트는(사람도) "설계 문서를 참고하라" 같은 언어 지시를 잘 따르지 않는다.
그래서 ai-harness는 지시가 아니라 구조로 강제한다.
규약(문서 폼·PR 형식)을 위반하면 커밋과 PR이 exit code로 차단된다.
검사기는 순수 룰(LLM 0)이라 결정적이며, 복사만 하면 바로 동작한다.

## 무엇을 막나

커밋·PR이 규약을 위반하면 훅이 이를 거부한다:

```text
$ git commit -m "docs 갱신"
[check_doc_form] 문서 폼 리젝 — 위반 1건:
  - docs/guide.md:12: 148자 > 80자 — 흐름을 우겨넣지 말고 쪼개라.
```

- **문서 폼** — 줄수·산문 80자·한 줄 한 문장·BLUF·손번호 좌표 금지
- **PR 본문** — 필수 섹션·섹션별 분량·내부 용어 풀이·확인 체크리스트
- **README 인덱스** — 폴더 BLUF 롤업 자동생성 + drift 검사

## 빠른 시작

```bash
# 1) core 스크립트 + gate_config.py 를 대상 저장소에 복사(또는 이 repo를 clone)
python3 scripts/install_hooks.py          # 2) pre-commit 훅 설치

# 3) (선택) AI 세션에서 PR 게이트까지 강제하려면
#    .claude/settings.json 의 PreToolUse 훅을 대상 저장소에 배치한다
```

## 채택하기

core 스크립트는 그대로 사용하고, `gate_config.py`만 대상 저장소에 맞춘다.
각 설정값의 의미는 `gate_config.py` 주석에 있다.
채택 절차와 정본 동기화 방법은 [docs/adopting.md](docs/adopting.md)를 참고한다.

## 검증

```bash
pytest    # 게이트 자기검증(무DB·무LLM·stdlib)
```
