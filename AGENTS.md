# AGENTS.md

> **BLUF:** ai-harness에서 에이전트가 따를 라우팅·작업 규약·검증 방법.

## 무엇을 만드나

저장소 공용 문서·PR 게이트다.

설치형 CLI(`ai-harness`)가 대상 저장소에서 돌고, 판정 로직은 stdlib만 쓴다.

소개는 [README.md](README.md), 채택 절차는 [docs/adopting.md](docs/adopting.md)가
정본이다.

## 어디를 보나

- 폴더마다 README.md가 그 안의 문서를 한 줄씩 안내한다(자동 생성).
- 게이트 동작의 정본은 코드다 — 문서와 어긋나면 문서가 낡은 것이다.
- 문서를 쓰기 전에 유형별 폼 `src/ai_harness/docs_format/<유형>.md`를 읽어라.
- 저장소 자기 규칙은 [docs/rules/](docs/rules/)에 있다.
- 여러 저장소가 함께 쓰는 공용 규칙 조문은 `src/ai_harness/rules/`가 정본이다.
- 그 조문은 패키지에 동봉돼 설치본과 함께 가지만, 소비 저장소가 그것을
  가리키게 하는 배포 수단은 아직 없다(후속 과제).
- 그 규칙이 왜 생겼는지는 [docs/history/](docs/history/)가 진다.

## 작업 규약

- 브랜치를 파고 PR로 올린다.
- PR 본문·리뷰 코멘트는 게이트를 통과해야 한다(형식은 게이트가 알려준다).
- 이슈 생성·PR 연결은
  [공용 규칙](src/ai_harness/rules/issue-reference-and-pr-linkage.md)을 따른다.
- 그 규칙대로 이슈를 만들기 전에 umbrella 여부를 제안한다.
- 문서를 고쳤으면 `ai-harness gen-readmes`로 인덱스를 갱신해 같이 커밋한다.
- 게이트 상수를 고쳤으면 `ai-harness gen-pr-template`로 템플릿도 다시 만든다.

## 검증

검증 명령은 [README.md](README.md)의 검증 절이 정본이다.

게이트를 고쳤으면 이 저장소 자신에게도 돌려 통과를 확인한다(도그푸딩).
