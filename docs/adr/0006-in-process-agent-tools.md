# ADR-0006: In-Process Agent Tools for the MVP

- Status: Accepted
- Date: 2026-08-12
- Decision owners: Project maintainer

## Context

현재 MVP는 하나의 Python 프로세스에서 로컬 PDF 한 개를 처리한다. 검색, Evidence Pack 구성, 답변 생성, Citation 검증이 이미 명확한 Python 서비스 경계로 분리되어 있다.

MCP 서버를 추가하면 외부 클라이언트와 프로세스 간 재사용성은 좋아지지만, 현재 범위에서는 서버 수명주기, 통신 오류, schema 배포와 통합 테스트 비용이 실제 사용자 가치보다 크다. 프로젝트의 우선 목표는 Agent의 재검색, 종료 제어, 답변 보류와 Citation 안전성을 검증하는 것이다.

## Decision

- MVP Agent는 검색과 답변 기능을 `Protocol` 기반 typed in-process tool로 호출한다.
- LangGraph는 상태, 조건부 분기, 재시도 한도와 종료 이유만 소유한다.
- 검색, Evidence Pack과 Citation 검증 로직은 Agent node 밖의 application service에 유지한다.
- MCP transport는 외부 프로세스나 다중 클라이언트 통합이 필요할 때 추가하는 후속 범위로 미룬다.
- REST API는 Agent 실행 결과와 재구성 가능한 trace를 노출한다.

## Consequences

### Positive

- 네트워크 계층 없이 Agent routing과 안전성에 집중할 수 있다.
- 같은 tool contract를 단위 테스트에서 직접 대체할 수 있다.
- MCP adapter를 나중에 추가해도 검색과 Citation 핵심 로직을 다시 구현할 필요가 없다.
- 로컬 실행과 CI가 단순하고 결정적이다.

### Negative

- 현재 도구는 다른 프로세스나 언어에서 직접 호출할 수 없다.
- MCP schema 호환성과 transport 장애 복구는 검증하지 않는다.
- 다중 클라이언트 운영으로 확장할 때 adapter와 별도 contract test가 필요하다.

## Alternatives Considered

### Retrieval, Document, Citation MCP 서버 구현

장기 확장성은 높지만 단일 프로세스 로컬 데모에 세 개의 transport 경계를 도입하는 것은 과도하다.

### Agent node에서 검색 로직 직접 구현

파일 수는 줄지만 Agent orchestration과 검색 책임이 결합되어 독립 테스트와 향후 MCP 전환이 어려워진다.

## Validation

- 첫 검색 성공, 재작성 후 성공, 재검색 한도 도달 경로 테스트
- 잘못된 Citation이 최종 답변에서 제거되는지 테스트
- Agent 없이 typed tool을 독립 호출할 수 있는지 테스트
- trace만으로 검색 모드, 검색어와 종료 이유를 재구성할 수 있는지 테스트

## Revisit Conditions

- Agent와 검색 서비스를 별도 프로세스로 배포하는 경우
- CLI, IDE 또는 다른 언어의 클라이언트가 같은 도구를 호출해야 하는 경우
- 여러 Agent가 공통 원격 도구 registry를 사용해야 하는 경우

## Related Documents

- [Agent & Tool Design](../agent-mcp-design.md)
- [ADR-0005: LangGraph Orchestration](./0005-langgraph-orchestration.md)

