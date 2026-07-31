# 규칙 00 — 이슈 참조와 PR 연결

> **BLUF:** 이슈를 umbrella와 단일로 가르고 PR 종료 키워드를 가려 쓰는 사항.

## 규칙

### 제1조 (이슈 분류)

이슈를 만들 때 상위 이슈의 sub-issue로 붙일지 정해야 한다.

sub-issue를 가진 이슈가 umbrella다 — 별도 라벨을 두지 않는다.

umbrella는 하위 과제가 모두 끝나야 닫을 수 있다.

### 제2조 (PR 종료 키워드)

PR이 그 이슈를 완결시키면 본문에 `Closes #N`을 써야 한다.

부분 기여이거나 umbrella를 가리킬 때는 `Refs #N`을 써야 한다.

다만 GitHub이 자동 종료로 인식하는 키워드는 `close`·`fix`·`resolve`
계열뿐이다.

### 제3조 (판단 주체)

이슈를 만들기 전에 umbrella 여부를 제안해 확정받아야 한다.

완결 여부가 모호하면 사람에게 확인해 확정해야 한다.

에이전트가 임의로 종료 키워드를 정해서는 아니 된다.

## 강제 수단 (정직 표기)

이슈 분류는 sub-issue 관계로 구조화된다(제1조) — 기록이 남는다.

다만 완결 여부 판정엔 기계 게이트가 없다.

무엇이 완결인지는 자연어 판단이라 룰로 검증할 수 없다.

따라서 그 축은 사람 확인과 리뷰어 판정에만 의존한다.

## 관련

- [게이트는 볼 수 있는 것만 판정한다](gates-judge-only-what-they-can-see.md)
  제1조 — 완결 여부가 사람만 아는 것에 속해 기계 게이트를 두지 않는 근거.
- [제정 근거가 된 실측 기록](https://github.com/pollux-o4-labs/ai-harness/blob/main/docs/history/B-refs-keyword-does-not-close-issue.md)
  — 여러 저장소가 함께 쓰는 조문이라 근거도 절대 주소로 가리킨다.
