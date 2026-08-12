# Documentation

이 디렉터리는 프로젝트 구현과 검증의 기준 문서를 관리한다. README는 프로젝트를 소개하고, 이 디렉터리의 문서는 **무엇을 만들고 어떻게 검증할지**를 정의한다.

## 권장 읽기 순서

1. [Requirements](./requirements.md) — 범위, 사용자 시나리오, 기능·비기능 요구사항
2. [Development Plan](./development-plan.md) — 14일 실행 일정과 작업 순서
3. [Sprint Runbook](./sprint-runbook.md) — Day 1~14 실행 체크리스트와 일일 Gate
4. [Architecture](./architecture.md) — 전체 시스템과 컴포넌트 경계
5. [Data Model](./data-model.md) — 문서, 페이지, 청크, 표, 인용 데이터 계약
6. [Ingestion Design](./ingestion-design.md) — PDF·OCR·표 처리 파이프라인
7. [Retrieval Design](./retrieval-design.md) — Dense, BM25, Hybrid, Reranking
8. [Agent & Tool Design](./agent-mcp-design.md) — LangGraph 상태와 내부 typed tool 계약
9. [API Contract](./api-contract.md) — 외부 API와 오류 응답
10. [Evaluation Plan](./evaluation-plan.md) — 평가 데이터와 품질 기준
11. [Testing Strategy](./testing-strategy.md) — 테스트 계층과 필수 회귀 시나리오
12. [Data Policy](./data-policy.md) — 문서 저작권, 보안, 보존 정책
13. [Operations](./operations.md) — 설정, 관측성, 배포, 장애 대응

## Architecture Decision Records

| ADR | 결정 |
| --- | --- |
| [ADR-0001](./adr/0001-page-centric-evidence-model.md) | 페이지 중심 근거 데이터 모델 |
| [ADR-0002](./adr/0002-hybrid-retrieval.md) | Qdrant와 OpenSearch를 이용한 Hybrid Retrieval |
| [ADR-0003](./adr/0003-document-parser-stack.md) | Docling, PyMuPDF, PaddleOCR 역할 분리 |
| [ADR-0004](./adr/0004-mcp-tool-boundaries.md) | MCP 서버 분리안(ADR-0006으로 대체) |
| [ADR-0005](./adr/0005-langgraph-orchestration.md) | LangGraph 기반 Agent orchestration |
| [ADR-0006](./adr/0006-in-process-agent-tools.md) | MVP용 in-process typed Agent tool |

## 문서 우선순위

서로 다른 문서의 내용이 충돌하면 다음 순서로 판단한다.

1. 승인된 ADR
2. `requirements.md`의 요구사항과 Acceptance Criteria
3. 세부 설계 문서
4. `development-plan.md`의 일정
5. 루트 `README.md`의 소개 내용

기술 결정이 바뀌면 먼저 ADR을 추가하거나 기존 ADR을 `Superseded`로 변경한 뒤 관련 문서를 수정한다.

## 공통 용어

| 용어 | 의미 |
| --- | --- |
| Document | 업로드된 하나의 논리 문서와 해당 버전 |
| Page | 사용자가 확인할 수 있는 PDF의 1-based 물리 페이지 |
| Element | 제목, 본문, 목록, 표, 그림 등 파싱된 레이아웃 단위 |
| Chunk | 검색 인덱싱을 위해 하나 이상의 Element를 묶은 단위 |
| Evidence | 답변의 주장을 지지하거나 반박하는 원문 근거 |
| Citation | Claim과 Evidence를 연결하는 검증 가능한 참조 |
| Retrieval | 질문에 관련된 Chunk 또는 Page를 찾는 과정 |
| Reranking | 1차 검색 후보의 관련성을 다시 평가하는 과정 |
| Abstention | 충분한 근거가 없을 때 답변을 보류하는 동작 |
| Agent | 질문에 따라 도구를 선택하고 재검색 여부를 결정하는 애플리케이션 |
| Typed Tool | 검색·근거·인용 기능을 Agent와 분리해 같은 프로세스에서 제공하는 인터페이스 |
| MCP Server | 후속 외부 통합에서 typed tool을 표준 프로토콜로 노출하는 서버 |

## 문서 관리 규칙

- 요구사항은 `FR-*`, 비기능 요구사항은 `NFR-*`, Acceptance Criteria는 `AC-*` ID를 사용한다.
- 코드와 테스트에는 관련 요구사항 ID를 주석이나 테스트 이름으로 남긴다.
- 미확정 내용은 확정된 사실처럼 쓰지 않고 `Open Question`으로 표시한다.
- 모델명, threshold, 인프라 크기는 설정으로 관리하고 문서에는 기본값과 변경 이유를 기록한다.
- 기능 PR은 관련 문서와 평가 기준을 함께 갱신한다.
