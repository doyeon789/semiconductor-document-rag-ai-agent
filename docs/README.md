# Documentation

이 디렉터리는 AI 보안 문서 RAG의 **현재 동작**, **품질 기준**, **다음 구현 범위**를 관리합니다. 구현되지 않은 대규모 인프라를 현재 기능처럼 설명하지 않습니다.

## 권장 읽기 순서

1. [Requirements](./requirements.md) — 제품 범위와 검증 가능한 요구사항
2. [Architecture](./architecture.md) — 현재 로컬 구조와 다음 다중 문서 구조
3. [Roadmap](./roadmap.md) — 날짜 대신 성능 병목 순서로 정리한 작업 목록
4. [Data Policy](./data-policy.md) — 코퍼스 출처, 이용 조건, Git 저장 원칙
5. [Ingestion Design](./ingestion-design.md) — 현재 PDF 추출과 다중 문서 수집 계약
6. [Retrieval Design](./retrieval-design.md) — BM25·Dense·Hybrid·Rerank 흐름
7. [Data Model](./data-model.md) — 페이지·Chunk·Evidence·Citation 계약
8. [API Contract](./api-contract.md) — 현재 FastAPI endpoint
9. [Evaluation Plan](./evaluation-plan.md) — AI 보안 평가셋과 품질 Gate
10. [Testing Strategy](./testing-strategy.md) — 현재 자동 테스트 계층
11. [Operations](./operations.md) — 로컬 실행과 장애 확인
12. [Local Demo Guide](./demo-guide.md) — 현재 단일 문서 데모의 실행법과 제한

## Architecture Decision Records

| ADR | 결정 |
| --- | --- |
| [ADR-0001](./adr/0001-page-centric-evidence-model.md) | 페이지 중심 근거 모델 |
| [ADR-0002](./adr/0002-hybrid-retrieval.md) | 로컬 BM25·Dense Hybrid Retrieval |
| [ADR-0003](./adr/0003-document-parser-stack.md) | PyMuPDF 우선 파서와 필요 기반 OCR |
| [ADR-0005](./adr/0005-langgraph-orchestration.md) | 제한된 LangGraph orchestration |
| [ADR-0006](./adr/0006-in-process-agent-tools.md) | 프로세스 내부 typed Agent tool |

MCP 서버 분리안은 현재 요구에 비해 복잡도가 크고 실제 구현에도 사용되지 않아 문서에서 제거했습니다. 외부 프로세스 통합이 실제 요구사항이 될 때 새 ADR로 다시 검토합니다.

## 문서 상태 표기

- **현재**: 코드와 테스트에서 동작하는 기능
- **다음**: 현재 코퍼스 전환을 완료하기 위해 바로 구현할 기능
- **후속**: 평가 결과가 필요성을 증명했을 때만 구현할 기능

문서가 코드와 충돌하면 테스트된 현재 구현을 기준으로 문서를 바로 수정합니다. 모델명, threshold와 평가 점수는 데이터셋·Git commit·설정과 함께 기록합니다.

## 공통 용어

| 용어 | 의미 |
| --- | --- |
| Corpus Source | `data/corpus/sources.yaml`에 등록된 공식 PDF 한 종 |
| Page | PDF 파일의 1-based 물리 페이지 |
| Element | PyMuPDF가 페이지에서 추출한 텍스트 블록 |
| Chunk | 검색에 사용하는 페이지 추적 가능한 텍스트 단위 |
| Evidence | 답변 후보로 선택한 문서·페이지 원문 |
| Citation | Claim과 Evidence의 문서·페이지·인용문 연결 |
| Abstention | 충분한 근거가 없을 때 답변하지 않는 정상 결과 |
| Agentic RAG | 제한된 횟수로 검색어를 바꾸고 재검색하는 LangGraph 경로 |
