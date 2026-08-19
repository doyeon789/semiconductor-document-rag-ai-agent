# ADR-0001: Page-Centric Evidence Model

- Status: Accepted
- Date: 2026-08-07
- Updated: 2026-08-19

## Context

사용자는 내부 Chunk ID가 아니라 실제 PDF 페이지에서 답변 근거를 확인합니다. 여러 문서를 함께 검색하면 페이지 번호만으로는 출처를 구분할 수 없습니다.

## Decision

- PDF 파일의 1-based 물리 페이지를 `page_number` 기준으로 사용합니다.
- Page, Element, Chunk, Evidence와 Citation에 같은 `version_id`를 전달합니다.
- 다중 문서 검색에서는 `document_id + version_id + page_number`를 근거 위치로 사용합니다.
- 현재 검색 Chunk와 Evidence는 한 물리 페이지 안에 유지합니다.
- Citation은 `document_id`, `version_id`, `chunk_id`, `page_number`와 정확한 `quote`를 가집니다.
- bbox를 얻는 Element에서는 원문 좌표를 보존합니다.

## Consequences

### Positive

- 답변에서 실제 PDF 페이지를 바로 열 수 있습니다.
- 같은 페이지 번호를 가진 다른 문서를 구분할 수 있습니다.
- 잘못된 페이지와 인용문을 자동 검증할 수 있습니다.
- parser·Chunk 정책이 바뀌어도 버전별 근거를 구분할 수 있습니다.

### Negative

- 페이지 경계를 넘는 설명은 여러 Evidence로 수집해야 합니다.
- 반복 header/footer와 목차가 페이지 검색을 오염시킬 수 있습니다.
- 모든 단계가 문서·버전 metadata를 빠뜨리지 않아야 합니다.

## Alternatives

- Chunk ID만 저장: 사용자가 원문을 확인하기 어려워 제외했습니다.
- 페이지 번호만 저장: 다중 문서에서 출처가 충돌해 제외했습니다.
- section만 저장: 실제 PDF 페이지 검증이 약해 제외했습니다.

## Validation

- 0-based/1-based 회귀 테스트
- 서로 다른 문서의 같은 페이지 번호 테스트
- Citation quote·문서·버전·페이지 일치 테스트
- Page Match Accuracy 평가
