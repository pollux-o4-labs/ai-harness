# 조문 저작 위임 프롬프트

> **BLUF:** 공용 규칙 조문 저작 위임용 보일러플레이트 — 공통 형식과 문장 규칙.

저장소: /home/pollux/work/pollux-o4-labs/ai-harness
여러 저장소가 함께 쓰는 공용 규칙 조문을 하나 새로 쓴다.

## 이 저장소 조문의 형식 — 그대로 따른다
1행: `# 규칙 NN — <제목>`
2행: 빈 줄
3행: `> **BLUF:** <한 줄>`
그다음 절 순서: `## 왜 필요한가` → `## 규칙` → `## 강제 수단 (정직 표기)` → `## 관련`
`## 규칙` 아래에는 `### 제1조 (소제목)` 형태의 소절을 둔다.

## 문장 규칙 — 기계 게이트가 검사한다
- 한 줄은 80자를 넘기지 않는다.
- 한 줄에 문장 하나만 쓴다.
- 문장 사이에 빈 줄을 넣는다.
- 조문 어미("~한다" / "~해야 한다")를 쓴다.
- 구어를 쓰지 마라.
- 한자어 계열로 통일한다.
- 줄표(—)로 문장 뒤에 부연을 붙이지 마라.
- 번역투를 쓰지 마라.
- 목적어 없는 타동사를 쓰지 마라.
- 전체 45줄 이내로 쓴다.
- 서사와 사례 나열을 넣지 마라.
- 조문만 쓴다.

## 외부 문헌 인용
본문에 외부 문헌을 인용하지 마라.
꼭 필요하면 `## 관련` 절에만 이름을 대고, 저장소 안 실측 근거가 없으면
"이 저장소 안의 실측 근거는 아직 없다" 고 정직하게 적어라.

## 기존 조문 목록 — 이 중에서만 상호 참조하라. 없는 조문을 지어내지 마라.
- 규칙 00 이슈 참조와 PR 연결 (issue-reference-and-pr-linkage.md)
- 규칙 01 게이트는 볼 수 있는 것만 판정한다 (gates-judge-only-what-they-can-see.md)
- 규칙 02 한 글에 한 어휘 층위 (one-register-per-document.md)
- 규칙 03 체크 전에 근거를 남긴다 (review-evidence-before-checking.md)
- 규칙 04 스코프가 겹치면 토픽 폴더로 묶는다 (topic-folders-when-scope-overlaps.md)
- 규칙 05 PR 본문의 구조와 분량 (pr-body-structure.md)
- 규칙 06 문서 저작 규범 (doc-authoring-norms.md)
- 규칙 07 규모별 작업 사이클과 커밋 전 적대검증 (work-cycle-by-size.md)
- 규칙 08 검사 기법 선택 (test-technique-selection.md)
- 규칙 09 에이전트 재사용 상한과 적대검증 (agent-reuse-cap.md)
- 규칙 10 다중 에이전트 역할 구성 (agent-role-roster.md)
- 규칙 11 파괴적 작업 전 백업과 전역 부작용 검증 (backup-before-destructive.md)
- 규칙 12 규약은 가장 좁은 자리에 둔다 (context-scope-narrowest.md)
- 규칙 13 반복된 구두 지시는 구조 결함 신호다 (repetition-is-a-structural-signal.md)

## 강제 수단 절
기계 게이트가 실제로 있는지 네가 판단하고 정직하게 적어라.
없으면 없다고 적어라.

있지도 않은 검사를 있다고 적으면 중대 결함이다.
