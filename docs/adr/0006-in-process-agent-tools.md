# ADR-0006: In-Process Agent Tools

- Status: Accepted
- Date: 2026-08-12
- Updated: 2026-08-19

## Context

검색, Evidence Pack, 추출형 답변과 Citation 검증은 Python 서비스로 이미 분리되어 있습니다. 현재 데모와 6개 문서 코퍼스는 한 프로세스에서 충분히 처리할 수 있습니다.

별도 tool server를 추가하면 수명주기, 통신, schema 배포와 장애 테스트 비용이 생기지만 현재 검색 품질이나 사용자 기능을 직접 개선하지 않습니다.

## Decision

- Agent는 `Protocol` 기반 typed in-process tool로 검색과 답변 기능을 호출합니다.
- LangGraph는 상태, 분기, 재시도와 종료 이유만 소유합니다.
- 검색·Evidence·Citation 핵심 로직은 Agent 밖에서 독립 테스트합니다.
- 외부 tool transport는 현재 범위에서 구현하지 않습니다.
- 외부 프로세스나 여러 클라이언트가 실제로 같은 도구를 공유해야 할 때 새 ADR로 검토합니다.

## Consequences

### Positive

- 네트워크 없이 결정적이고 빠른 테스트가 가능합니다.
- 검색 품질과 Citation 안전성에 집중할 수 있습니다.
- 도구 구현을 Agent 없이 직접 사용할 수 있습니다.

### Negative

- 다른 프로세스나 언어가 도구를 원격 호출할 수 없습니다.
- process isolation과 transport 장애 복구를 검증하지 않습니다.

## Alternatives

- 원격 tool server: 현재 요구보다 복잡해 제외했습니다.
- Agent node에 검색 로직 직접 작성: 책임이 결합돼 제외했습니다.

## Validation

- fake tool을 사용한 Agent routing 테스트
- Agent 없이 검색·답변 tool 직접 호출 테스트
- timeout·오류·답변 보류 경로 테스트
- trace로 전체 tool 흐름 재구성 테스트

## Related Decisions

- [ADR-0005: Bounded LangGraph Orchestration](./0005-langgraph-orchestration.md)
