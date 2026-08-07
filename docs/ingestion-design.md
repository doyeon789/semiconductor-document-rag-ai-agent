# Ingestion Design

## 1. 목표

PDF의 텍스트, 레이아웃, 표, 페이지 번호를 보존하면서 검색 가능한 Chunk를 생성한다. 파싱 품질이 낮은 페이지는 OCR로 보완하고, 일부 페이지 실패가 전체 문서 처리를 중단하지 않도록 한다.

## 2. Parser 역할

| 도구 | 역할 |
| --- | --- |
| PyMuPDF | PDF 열기, 물리 페이지 수·크기 확인, text block·좌표 추출, 페이지 렌더링 |
| Docling | 문서 구조, 읽기 순서, 제목·본문·표 레이아웃 분석 |
| PaddleOCR | 텍스트가 부족한 한국어·영어 스캔 페이지의 OCR fallback |

PyMuPDF가 페이지 번호와 이미지 렌더링의 기준이 된다. Docling 결과는 페이지와 bbox를 이용해 기준 페이지에 매핑한다. OCR은 자동 감지된 페이지에만 적용한다.

## 3. Pipeline

```mermaid
flowchart LR
    A["Validate Upload"] --> B["Fingerprint"]
    B --> C["Store Original"]
    C --> D["Inspect Pages"]
    D --> E["Layout Parse"]
    E --> F{"OCR Needed?"}
    F -->|Yes| G["Render + OCR"]
    F -->|No| H["Normalize Elements"]
    G --> H
    H --> I["Extract Tables"]
    I --> J["Build Chunks"]
    J --> K["Quality Checks"]
    K --> L["Persist Metadata"]
    L --> M["Build Indexes"]
    M --> N["Activate Version"]
```

## 4. 단계별 계약

### 4.1 Validate Upload

- 허용 확장자: `.pdf`
- MIME type과 `%PDF-` signature를 함께 확인한다.
- 파일명은 표시용 metadata로만 사용한다.
- 저장 object key는 서버가 생성한다.
- 최대 크기와 최대 페이지 수는 환경변수로 제한한다.
- 암호화 PDF는 지원 여부를 판정하고 구조화된 오류를 반환한다.

초기 기본값:

```yaml
max_file_size_mb: 100
max_pages: 1000
allowed_mime_types:
  - application/pdf
```

### 4.2 Fingerprint & Idempotency

```text
content_sha256 = SHA256(original_file_bytes)
parser_config_hash = SHA256(canonical_json(parser_config))
idempotency_key = content_sha256 + ":" + parser_config_hash
```

- 동일 key의 성공 버전이 있으면 기존 결과를 반환한다.
- 실패 버전은 명시적 retry 요청에서 재처리한다.
- parser version이 바뀌면 새 `parser_config_hash`를 생성한다.

### 4.3 Page Inspection

각 페이지에서 다음 값을 계산한다.

- 문자 수와 단어 수
- text block 수
- text bbox 면적 비율
- 이미지 면적 비율
- 글꼴과 회전 정보
- 반복 header/footer 후보
- 이미지 렌더링 필요 여부

초기 OCR 판정 규칙은 설정값으로 둔다.

```yaml
ocr:
  min_text_characters: 40
  min_text_blocks: 2
  max_text_coverage_for_scan: 0.002
  dpi: 200
  languages: [ko, en]
```

셋 중 두 조건 이상이 부족하거나 text extraction 오류가 발생하면 OCR 후보로 지정한다. 최종 threshold는 평가 문서로 조정한다.

### 4.4 Layout Parse

Element에 다음 정보를 저장한다.

```json
{
  "element_type": "paragraph",
  "page_number": 12,
  "reading_order": 8,
  "bbox": [72.1, 180.0, 510.2, 244.8],
  "text": "Normalized text",
  "parser_confidence": 0.96
}
```

정규화 규칙:

- Unicode NFKC 정규화
- 연속 공백과 줄바꿈 정리
- 페이지 끝 하이픈 연결은 사전·문맥 조건을 만족할 때만 수행
- `°C`, `μm`, `Å`, `%`, 화학식의 기호를 보존
- 숫자, 단위, 장비 코드의 대소문자를 임의 변환하지 않음
- 반복 header/footer는 별도 Element로 유지하되 검색 Chunk에서 제외

### 4.5 OCR Merge

- OCR 결과는 원본 페이지 좌표로 변환한다.
- 기존 text block과 IoU가 높은 OCR block은 중복으로 제거한다.
- native text와 OCR text가 충돌하면 source와 confidence를 모두 기록한다.
- 평균 confidence가 기준보다 낮아도 원문은 보존하되 `quality_warning`을 생성한다.
- OCR을 사용한 페이지는 답변 Citation에서 사용자에게 표시할 수 있다.

### 4.6 Table Extraction

표는 구조화 JSON과 검색용 Markdown을 함께 생성한다.

```json
{
  "caption": "Table 2. Etch conditions",
  "header": ["Recipe", "Pressure (mTorr)", "Selectivity"],
  "rows": [
    ["A", "20", "8.4"],
    ["B", "30", "10.1"]
  ],
  "page_number": 7
}
```

검색용 표현:

```text
[Table] Table 2. Etch conditions
Recipe=A | Pressure (mTorr)=20 | Selectivity=8.4
Recipe=B | Pressure (mTorr)=30 | Selectivity=10.1
```

- 각 행은 열 이름을 반복해 의미를 보존한다.
- 긴 표는 header를 유지하며 행 그룹 단위로 분할한다.
- 다중 페이지 표는 caption·header 연속성과 좌표를 근거로 병합하되 원래 페이지 범위를 기록한다.
- 병합 confidence가 낮으면 별도 표로 유지한다.

## 5. Chunking Strategy

### 5.1 기본 정책

```yaml
chunking:
  target_tokens: 450
  min_tokens: 120
  max_tokens: 700
  overlap_tokens: 60
  max_page_span: 2
```

### 5.2 알고리즘

1. 제목 계층으로 `section_path`를 구성한다.
2. Element의 reading order를 유지한다.
3. 같은 section과 page의 연속 Element를 target token까지 결합한다.
4. 문단 중간보다 문장·목록 경계에서 분할한다.
5. 페이지 경계를 만나면 원칙적으로 Chunk를 종료한다.
6. 문장이 다음 페이지로 이어지는 경우에만 두 페이지 Chunk를 허용한다.
7. 표는 일반 본문과 분리해 전용 Chunk를 생성한다.
8. Chunk prefix에 문서 제목과 section path를 추가하되 `raw_text`와 `index_text`를 구분한다.

```text
index_text = document_title + section_path + content_type_hint + raw_text
```

### 5.3 중복 제거

- `content_hash`가 동일한 반복 Chunk를 후보로 표시한다.
- 문서 내부 반복 boilerplate는 색인하지 않되 metadata에는 남긴다.
- 다른 문서의 동일 문장은 삭제하지 않는다. 다중 문서 비교에서 출처 구분이 필요하기 때문이다.

## 6. Persistence & Indexing

### 6.1 처리 순서

1. 원본 PDF 저장
2. DocumentVersion, Page, Element, Table, Chunk를 transaction으로 저장
3. Qdrant 임시 collection/namespace에 Dense index 작성
4. OpenSearch 임시 index/alias 대상에 BM25 index 작성
5. 색인 건수와 DB Chunk 건수 비교
6. smoke query 실행
7. 활성 버전과 alias 전환

검색 인덱스 실패 시 DB metadata를 삭제하지 않는다. 상태를 `INDEX_FAILED`로 바꾸고 재색인 job을 생성한다.

### 6.2 Artifact Layout

```text
documents/{document_id}/{version_id}/original.pdf
documents/{document_id}/{version_id}/pages/{page_number}.png
documents/{document_id}/{version_id}/parsed/elements.jsonl
documents/{document_id}/{version_id}/parsed/tables.jsonl
documents/{document_id}/{version_id}/reports/quality.json
```

## 7. Quality Report

문서 처리 완료 시 다음 지표를 기록한다.

| Metric | 설명 |
| --- | --- |
| `parsed_page_ratio` | 정상 파싱 페이지 비율 |
| `ocr_page_ratio` | OCR 사용 페이지 비율 |
| `low_confidence_ocr_ratio` | OCR confidence 미달 비율 |
| `empty_page_ratio` | 빈 페이지 비율 |
| `table_count` | 추출 표 수 |
| `chunk_count` | 생성 Chunk 수 |
| `orphan_element_count` | Chunk에 연결되지 않은 검색 대상 Element 수 |
| `index_count_match` | DB와 검색 인덱스 건수 일치 여부 |

초기 배포 차단 조건:

- `parsed_page_ratio < 0.95`
- `index_count_match = false`
- 페이지 번호 불변식 위반
- 모든 검색 대상 Chunk가 빈 문자열

## 8. Failure Handling

| Failure | 처리 |
| --- | --- |
| 손상된 PDF | `INVALID_PDF`로 종료, 사용자 메시지 제공 |
| 암호화 PDF | `ENCRYPTED_PDF`로 종료 또는 password 지원 단계로 전달 |
| 개별 페이지 렌더링 실패 | 페이지 오류 기록 후 계속 처리 |
| OCR timeout | 낮은 품질 상태로 native parse 유지, 재시도 가능 |
| 표 파싱 실패 | 이미지·원문 text fallback과 warning 저장 |
| Qdrant 실패 | metadata 유지, index retry |
| OpenSearch 실패 | metadata 유지, index retry |

## 9. Test Fixtures

- 영문 논문 2단 레이아웃
- 한국어 텍스트 PDF
- 한국어·영어 혼합 스캔 PDF
- 회전된 페이지
- 표가 있는 공정 문서
- 여러 페이지에 걸친 표
- header/footer가 반복되는 매뉴얼
- 빈 페이지와 이미지 전용 페이지
- 수식, 단위, 특수문자가 포함된 문서

## 10. Definition of Done

- [ ] FR-ING-001~008 관련 테스트가 존재한다.
- [ ] 모든 Chunk의 원문 페이지를 API로 조회할 수 있다.
- [ ] 재처리 idempotency 테스트가 통과한다.
- [ ] OCR과 표 fixture가 자동 테스트에 포함된다.
- [ ] DB와 두 검색 인덱스 건수가 검증된다.
- [ ] 문서별 quality report가 생성된다.

## 11. 관련 문서

- [Data Model](./data-model.md)
- [Testing Strategy](./testing-strategy.md)
- [ADR-0003](./adr/0003-document-parser-stack.md)

