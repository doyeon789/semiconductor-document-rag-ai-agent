# ADR-0001: Page-Centric Evidence Model

- Status: Accepted
- Date: 2026-08-07
- Decision owners: Project maintainer

## Context

RAG 시스템은 보통 token Chunk를 검색 단위로 사용하지만 사용자는 Chunk ID가 아니라 실제 PDF 페이지를 확인한다. PDF 내부 페이지와 문서에 인쇄된 페이지 표기가 다를 수 있고, 표·문장이 여러 페이지에 걸칠 수 있다. Chunk만 저장하면 답변의 근거를 원문에서 재현하기 어렵다.

## Decision

- PDF의 물리 페이지를 1-based `page_number`의 기준으로 사용한다.
- 인쇄된 페이지 표기는 `printed_page_label`에 별도로 저장한다.
- `DocumentVersion → Page → Element → Chunk` 관계를 metadata source of truth로 저장한다.
- 모든 Chunk는 `version_id`, `page_start`, `page_end`, `element_ids`를 가진다.
- Citation은 특정 `document_id`, `version_id`, `page_number`, `chunk_id`를 참조한다.
- bbox를 얻을 수 있을 때 Evidence 위치를 저장한다.
- 기본 Chunk는 한 페이지에 속하고 문장이 이어질 때만 최대 두 페이지를 허용한다.

## Consequences

### Positive

- 사용자가 답변에서 실제 원문 페이지로 이동할 수 있다.
- 잘못된 페이지 인용을 자동 검증할 수 있다.
- 문서가 재색인되어도 답변 당시 version을 재현할 수 있다.
- 표와 OCR 결과의 품질 문제를 페이지 단위로 추적할 수 있다.

### Negative

- 페이지 경계에서 문맥이 끊길 수 있어 인접 Chunk 결합이 필요하다.
- bbox와 Element 저장으로 metadata가 증가한다.
- parser 간 페이지·좌표 mapping 검증이 필요하다.

## Alternatives Considered

### Chunk-only model

구현은 단순하지만 실제 페이지 근거를 안정적으로 재현하기 어렵기 때문에 제외한다.

### Section-only model

논문 구조에는 적합하지만 장비 매뉴얼의 페이지 참조와 표 위치 검증이 약해 제외한다.

## Validation

- 모든 Chunk의 원문 페이지 API 조회 테스트
- 0/1-based page regression test
- Citation Page Match Accuracy 평가
- 재색인 후 과거 `version_id` Citation 재현 테스트

## Related Documents

- [Data Model](../data-model.md)
- [Requirements](../requirements.md)

