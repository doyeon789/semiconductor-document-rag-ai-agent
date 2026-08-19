# ADR-0003: PyMuPDF-First Parsing

- Status: Accepted
- Date: 2026-08-07
- Updated: 2026-08-19

## Context

페이지 Citation이 정확하려면 물리 페이지 순서와 텍스트 좌표의 기준이 하나여야 합니다. 초기 설계는 Docling과 PaddleOCR까지 포함했지만, 현재 AI 보안 코퍼스의 핵심 본문은 PyMuPDF 네이티브 텍스트로 추출됩니다.

## Decision

- PyMuPDF를 물리 페이지, 크기, native text block, bbox와 읽기 순서의 기준으로 사용합니다.
- 네이티브 텍스트가 없는 페이지는 자동 OCR하지 않고 먼저 시각 검사합니다.
- 표지·이미지 목차·장 구분 간지·공백은 `excluded_pages`로 기록합니다.
- OCR이나 별도 layout parser는 정답 근거가 추출되지 않는 평가 실패가 확인될 때 추가합니다.
- parser source와 block number를 Element metadata에 기록합니다.

## Consequences

### Positive

- 의존성과 실행 시간이 작고 페이지 mapping이 단순합니다.
- 현재 773쪽 코퍼스의 핵심 본문을 처리할 수 있습니다.
- OCR이 필요하지 않은 장식 페이지에 비용을 쓰지 않습니다.

### Negative

- 이미지 안의 목차 글자와 복잡한 표 구조를 검색하지 못합니다.
- heading, list, table을 모두 paragraph block으로 취급할 수 있습니다.
- 다단 레이아웃의 읽기 순서가 항상 완벽하지 않습니다.

## Alternatives

- 모든 페이지 OCR: 중복 text와 비용이 증가해 제외했습니다.
- Docling 기본 파서: 현재 병목이 입증되지 않아 보류했습니다.
- Cloud Document AI: 비용·외부 전송·재현성 때문에 현재 범위에서 제외했습니다.

## Revisit Conditions

- gold page의 핵심 정보가 이미지에만 존재하는 경우
- 표 구조 손실이 질문 실패의 주원인인 경우
- PyMuPDF 읽기 순서가 검색 품질을 반복적으로 낮추는 경우

## Validation

- 실제 페이지 수와 매니페스트 비교
- Element text·bbox·reading order 테스트
- 제외 페이지 시각 검수 기록
- parser 변경 전후 gold page 검색 지표 비교
