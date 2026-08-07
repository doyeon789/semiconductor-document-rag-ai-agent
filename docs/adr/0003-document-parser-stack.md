# ADR-0003: Document Parser Stack

- Status: Accepted
- Date: 2026-08-07
- Decision owners: Project maintainer

## Context

단일 PDF library로 텍스트 추출, 물리 페이지 검증, 복잡한 레이아웃, 표, 한국어·영어 OCR을 모두 안정적으로 처리하기 어렵다. 여러 parser 결과를 무분별하게 혼합하면 페이지 번호와 읽기 순서가 깨질 수 있다.

## Decision

- PyMuPDF를 물리 페이지, 크기, native text block, bbox, 페이지 이미지의 기준으로 사용한다.
- Docling을 문서 구조, 읽기 순서, 제목·본문·표 분석에 사용한다.
- PaddleOCR을 텍스트 부족 페이지의 한국어·영어 OCR fallback으로 사용한다.
- OCR은 전체 문서가 아니라 page inspection 기준을 만족하는 페이지만 수행한다.
- parser 결과를 공통 `Page`와 `Element` schema로 정규화한다.
- 파서·OCR 결과의 source와 confidence를 metadata에 기록한다.

## Consequences

### Positive

- 페이지 추적, 레이아웃, OCR 역할이 명확하다.
- 스캔 페이지에만 OCR을 적용해 비용을 줄인다.
- parser adapter별 fixture와 품질 지표를 만들 수 있다.

### Negative

- 여러 라이브러리 설치와 모델 cache가 필요하다.
- Docling/OCR 좌표를 PyMuPDF 페이지 좌표에 맞추는 로직이 필요하다.
- parser version 호환성 관리가 필요하다.

## Alternatives Considered

### PyMuPDF only

페이지와 native text는 강하지만 복잡한 표·레이아웃과 OCR 품질이 부족하다.

### Docling only

구조 분석은 유리하지만 페이지 렌더링과 source-of-truth 검증을 독립 도구로 유지할 필요가 있다.

### Cloud Document AI

높은 품질 가능성이 있지만 비용, 외부 전송, 재현성, 포트폴리오 실행 장벽 때문에 MVP 기본값에서 제외한다.

## Validation

- text, scan, two-column, single/multi-page table fixture
- parser/OCR page mapping test
- OCR confidence와 핵심 token 보존 측정
- parser version 변경 시 golden diff review

## Related Documents

- [Ingestion Design](../ingestion-design.md)
- [Data Policy](../data-policy.md)

