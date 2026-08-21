# ADR-0005: Bounded LangGraph Orchestration

- Status: Accepted
- Date: 2026-08-07
- Updated: 2026-08-19

## Context

첫 검색이 약할 때 검색어를 바꾸고 다시 검색해야 하지만, 자유로운 Agent loop는 무한 재검색과 종료 이유 불명확 문제를 만들 수 있습니다.

## Decision

- LangGraph로 입력 안전 분류, 검색, 충분성 판단, query rewrite, 답변 검증과 종료를 명시합니다.
- 첫 검색은 BM25, 필요한 한 번의 개선 검색은 Rerank를 기본 경로로 사용합니다.
- `max_steps`, `max_retrieval_attempts`, `max_repair_attempts`와 tool timeout을 요청 schema로 제한합니다.
- 검색·Evidence·답변 로직은 graph node에 복사하지 않고 typed in-process tool로 호출합니다.
- 모든 실행은 검색어, 검색 모드, step과 종료 이유를 trace로 반환합니다.

## Consequences

### Positive

- 재검색과 답변 보류 경로를 자동 테스트할 수 있습니다.
- 최대 실행량과 timeout을 강제할 수 있습니다.
- Native RAG와 Agentic RAG의 결과·비용을 비교할 수 있습니다.

### Negative

- 고정 RAG chain보다 상태와 테스트 코드가 많습니다.
- 현재 도구가 검색과 답변으로 제한돼 복잡한 계획 능력은 없습니다.
- Agent가 실제 품질을 개선하지 못하면 유지 비용만 남을 수 있습니다.

## Alternatives

- 단일 고정 chain: baseline으로 유지하지만 재검색 경로를 표현하기 어렵습니다.
- 자유 ReAct loop: 실행 상한과 재현성이 약해 제외했습니다.
- 자체 state machine: 현재 LangGraph보다 명확한 이점이 없어 선택하지 않았습니다.

## Revisit Conditions

- 새 평가셋에서 Agentic RAG가 Native RAG보다 개선되지 않는 경우
- 모든 질문이 한 번의 Rerank 검색으로 충분한 경우
- LangGraph 의존성이 배포나 유지보수를 불필요하게 어렵게 하는 경우

## Validation

- 첫 검색 성공·재검색 성공·검색 한도 도달 경로
- prompt injection, step limit, timeout과 tool error 경로
- Trajectory Accuracy와 평균 retrieval attempts
