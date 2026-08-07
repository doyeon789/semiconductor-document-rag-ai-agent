# ADR-0005: LangGraph Orchestration

- Status: Accepted
- Date: 2026-08-07
- Decision owners: Project maintainer

## Context

질문에 따라 단일 검색, 문서별 검색, 표 조회, 재검색, Citation repair, 답변 보류 경로가 달라진다. 자유로운 ReAct loop만 사용하면 무한 도구 호출과 종료 이유를 통제하기 어렵고 평가 trajectory를 재현하기 어렵다.

## Decision

- LangGraph로 Agent의 상태와 조건부 전이를 구현한다.
- 질문 분류, 검색 계획, 검색, 재작성, 원문 수집, 답변 생성, Citation 검증, repair, abstention을 명시적 node로 나눈다.
- `max_steps`, `max_retrieval_attempts`, `max_tool_errors`, timeout을 설정한다.
- 검색 알고리즘과 Citation 검증은 Agent node가 아니라 application/MCP 도구에 둔다.
- 최종 종료 이유를 enum으로 반환한다.

## Consequences

### Positive

- 재검색·오류 복구·답변 보류 경로가 코드와 diagram에 명시된다.
- node와 edge 단위 테스트가 가능하다.
- tool 선택과 retry trajectory를 평가할 수 있다.
- 무한 loop와 과도한 tool call을 제한할 수 있다.

### Negative

- 단순 RAG chain보다 상태와 routing 코드가 많다.
- state schema 변경에 migration 성격의 관리가 필요하다.
- LangGraph API version과 runtime 특성을 추적해야 한다.

## Alternatives Considered

### 단일 prompt + retrieval chain

단일 질문에는 충분하지만 다중 도구·재검색·검증 요구사항을 명시적으로 관리하기 어렵다.

### 자유 ReAct loop

유연하지만 종료 조건, 재현성, 비용 상한, trajectory 평가가 약하다.

### 자체 state machine

의존성은 줄지만 checkpoint, tracing, graph 구성을 직접 구현해야 한다.

## Validation

- 모든 routing edge unit test
- max step/timeout/retry test
- trajectory dataset 기반 Tool Selection Accuracy
- 불필요한 tool call과 termination accuracy 측정

## Revisit Conditions

- Agent 경로가 실제로 단일 고정 chain으로 수렴하는 경우
- LangGraph 의존성이 배포 제약을 크게 증가시키는 경우
- 더 단순한 state machine이 같은 평가·관측성 요구를 충족하는 경우

## Related Documents

- [Agent & MCP Design](../agent-mcp-design.md)
- [Evaluation Plan](../evaluation-plan.md)

