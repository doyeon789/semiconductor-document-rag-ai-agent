# ADR-0004: MCP Tool Boundaries

- Status: Accepted
- Date: 2026-08-07
- Decision owners: Project maintainer

## Context

Agent 내부에 검색, DB 조회, 원문 처리, 인용 검증을 직접 구현하면 각 기능을 독립적으로 평가하기 어렵고 Agent prompt와 infrastructure code가 강하게 결합된다. 프로젝트 목표에는 Function Calling과 MCP 도구 연동이 포함된다.

## Decision

기능을 세 MCP 서버로 분리한다.

1. Retrieval MCP Server — Hybrid Search, 문서 내 검색, 표 검색, 용어 확장
2. Document MCP Server — 문서 metadata, 페이지, Chunk 주변 문맥, 표 원문 조회
3. Citation MCP Server — Claim-Evidence support, 페이지·quote·version 검증

각 MCP tool은 application use case를 호출하는 얇은 adapter로 구현한다. 비즈니스 로직을 MCP handler에 작성하지 않는다.

## Consequences

### Positive

- 도구를 Agent 없이 독립적으로 호출·테스트할 수 있다.
- API, CLI, Agent가 동일 use case를 재사용할 수 있다.
- Agent trajectory에서 어떤 기능이 실패했는지 분리할 수 있다.
- MCP client를 지원하는 다른 host에서 도구 재사용이 가능하다.

### Negative

- 서버 lifecycle과 연결 오류를 관리해야 한다.
- JSON serialization과 네트워크/프로세스 비용이 추가된다.
- tool schema versioning이 필요하다.

## Alternatives Considered

### 하나의 MCP Server

초기 구성은 단순하지만 역할과 권한 경계가 모호해지고 개별 장애 격리가 어렵다.

### Python function 직접 호출만 사용

가장 단순하지만 MCP 도구 재사용과 contract test 목표를 충족하지 않는다.

### MCP handler에 모든 로직 구현

빠르게 시작할 수 있지만 application layer를 우회해 REST API와 구현이 중복된다.

## Validation

- MCP schema contract tests
- 각 서버 독립 health/smoke test
- Agent 없이 tool 호출 E2E
- 서버별 timeout과 typed error recovery test

## Revisit Conditions

- 3개 프로세스 분리가 데모 배포를 불가능하게 만드는 경우 같은 프로세스 내 서버로 배치하되 논리적 schema 경계는 유지한다.

## Related Documents

- [Agent & MCP Design](../agent-mcp-design.md)
- [Architecture](../architecture.md)

