# API Contract

## 1. 원칙

- Base path는 `/v1`을 사용한다.
- 외부 응답은 Pydantic schema로 검증한다.
- ID, page number, status는 자유 형식 문자열이 아닌 typed field로 제공한다.
- 모든 응답에 `request_id` 또는 `trace_id`를 포함한다.
- 시간이 오래 걸리는 ingestion·evaluation은 job resource로 모델링한다.
- MVP answer API는 비스트리밍을 기본으로 하며, streaming은 후속 endpoint로 추가한다.

## 2. 공통 헤더

| Header | 방향 | 설명 |
| --- | --- | --- |
| `X-Request-ID` | Request/Response | 없으면 서버가 생성 |
| `Idempotency-Key` | Request | 문서 등록 등 재시도 가능한 쓰기 요청 |
| `X-Trace-ID` | Response | Agent·검색 trace 식별자 |

## 3. Common Error

```json
{
  "error": {
    "code": "DOCUMENT_NOT_READY",
    "message": "The document has not finished indexing.",
    "details": {
      "document_id": "doc-1",
      "status": "INDEXING"
    },
    "retryable": true
  },
  "request_id": "request-1"
}
```

| HTTP | Code | 의미 |
| ---: | --- | --- |
| 400 | `INVALID_REQUEST` | schema 외 의미 검증 실패 |
| 400 | `INVALID_PDF` | PDF signature 또는 구조 오류 |
| 400 | `ENCRYPTED_PDF` | 지원하지 않는 암호화 PDF |
| 404 | `DOCUMENT_NOT_FOUND` | 문서 없음 또는 접근 불가 |
| 404 | `PAGE_NOT_FOUND` | 실제 페이지 범위 밖 |
| 409 | `DOCUMENT_NOT_READY` | 파싱·색인 미완료 |
| 409 | `VERSION_CONFLICT` | stale document/index version |
| 413 | `FILE_TOO_LARGE` | 업로드 제한 초과 |
| 422 | `VALIDATION_ERROR` | Pydantic/JSON Schema 오류 |
| 429 | `RATE_LIMITED` | 요청 제한 초과 |
| 502 | `DEPENDENCY_ERROR` | 검색·LLM·storage 오류 |
| 504 | `TIMEOUT` | 요청 시간 초과 |

## 4. Documents

### 4.1 `POST /v1/documents`

PDF를 등록하고 비동기 ingestion job을 생성한다.

Request: `multipart/form-data`

| Field | Type | Required |
| --- | --- | :---: |
| `file` | PDF binary | ✓ |
| `title` | string |  |
| `document_type` | enum |  |
| `language` | enum |  |
| `source_uri` | string |  |
| `license_type` | string |  |

Response `202 Accepted`:

```json
{
  "document_id": "doc-1",
  "version_id": "version-1",
  "job_id": "job-1",
  "status": "UPLOADED",
  "request_id": "request-1"
}
```

동일 `Idempotency-Key` 또는 동일 파일·파서 설정이면 기존 version/job을 반환할 수 있다.

### 4.2 `GET /v1/documents`

Query parameters:

```text
status, document_type, language, cursor, limit
```

### 4.3 `GET /v1/documents/{document_id}`

```json
{
  "document_id": "doc-1",
  "title": "Equipment Manual",
  "document_type": "manual",
  "language": "en",
  "active_version": {
    "version_id": "version-1",
    "status": "READY",
    "page_count": 120,
    "parser_version": "parser@sha"
  },
  "quality": {
    "parsed_page_ratio": 1.0,
    "ocr_page_ratio": 0.1,
    "table_count": 14,
    "chunk_count": 620
  }
}
```

### 4.4 `GET /v1/documents/{document_id}/pages/{page_number}`

Query:

- `version_id`: 생략 시 active version
- `include_elements`: 기본 `true`
- `include_image_url`: 기본 `true`

Response:

```json
{
  "document_id": "doc-1",
  "version_id": "version-1",
  "page_number": 42,
  "printed_page_label": "4-12",
  "text": "...",
  "elements": [],
  "image_url": "/v1/documents/doc-1/pages/42/image",
  "ocr_used": false
}
```

### 4.5 `DELETE /v1/documents/{document_id}`

후속 관리 기능이다. metadata soft delete와 검색 비활성화를 즉시 수행하고 binary/index 정리는 비동기 job으로 처리한다. 실제 도입 전 접근 제어를 구현해야 한다.

## 5. Jobs

### `GET /v1/jobs/{job_id}`

```json
{
  "job_id": "job-1",
  "job_type": "INGESTION",
  "status": "INDEXING",
  "progress": {
    "stage": "qdrant_index",
    "completed": 540,
    "total": 620
  },
  "warnings": [],
  "error": null,
  "created_at": "2026-08-07T00:00:00Z",
  "updated_at": "2026-08-07T00:02:00Z"
}
```

## 6. Search

### `POST /v1/search`

Request:

```json
{
  "query": "Vacuum Interlock 원인과 조치 절차",
  "filters": {
    "document_ids": ["doc-1"],
    "document_types": ["manual"],
    "languages": ["en", "ko"]
  },
  "intent": null,
  "top_k": 8,
  "include_debug_scores": false
}
```

Response:

```json
{
  "query_id": "query-1",
  "retrieval_run_id": "retrieval-1",
  "intent": "procedure",
  "expansions": [],
  "sufficiency": "SUFFICIENT",
  "results": [
    {
      "rank": 1,
      "chunk_id": "chunk-1",
      "document_id": "doc-1",
      "version_id": "version-1",
      "document_title": "Equipment Manual",
      "page_start": 42,
      "page_end": 42,
      "section_path": ["Troubleshooting", "Vacuum Interlock"],
      "content_type": "text",
      "highlight": "Check chamber pressure and vacuum valve status.",
      "scores": null
    }
  ],
  "latency_ms": 410,
  "request_id": "request-1"
}
```

## 7. Answers

### `POST /v1/answers`

Request:

```json
{
  "question": "두 문서에서 ALD와 CVD 온도 조건을 비교해줘",
  "filters": {
    "document_ids": ["doc-1", "doc-2"]
  },
  "audience": "researcher",
  "include_retrieval_summary": true
}
```

Response:

```json
{
  "answer": "문서 A는 ... 반면 문서 B는 ...",
  "abstained": false,
  "abstention_reason": null,
  "claims": [
    {
      "claim_id": "claim-1",
      "text": "문서 A의 ALD 조건은 250°C이다.",
      "citation_ids": ["citation-1"],
      "inference": false
    }
  ],
  "citations": [
    {
      "citation_id": "citation-1",
      "document_id": "doc-1",
      "version_id": "version-1",
      "document_title": "ALD Process Guide",
      "page_number": 12,
      "printed_page_label": null,
      "quote": "The deposition temperature was 250°C.",
      "chunk_id": "chunk-1",
      "support": "supports"
    }
  ],
  "retrieval_summary": {
    "attempts": 2,
    "evidence_count": 6,
    "sufficiency": "SUFFICIENT"
  },
  "termination_reason": "ANSWER_VALIDATED",
  "trace_id": "trace-1",
  "request_id": "request-1"
}
```

### Abstention Response

HTTP status는 정상적인 제품 동작이므로 `200 OK`를 사용한다.

```json
{
  "answer": null,
  "abstained": true,
  "abstention_reason": {
    "code": "EVIDENCE_INSUFFICIENT",
    "message": "등록된 문서에서 질문을 뒷받침할 근거를 찾지 못했습니다.",
    "missing_information": ["해당 장비 모델의 maintenance manual"]
  },
  "claims": [],
  "citations": [],
  "termination_reason": "RETRIEVAL_LIMIT_REACHED",
  "trace_id": "trace-2"
}
```

## 8. Evaluations

### `POST /v1/evaluations/runs`

```json
{
  "dataset_id": "eval-v1",
  "configuration_id": "hybrid-rerank-v1",
  "suites": ["retrieval", "citation", "agent"]
}
```

Response: `202 Accepted` with `job_id` and `evaluation_run_id`.

### `GET /v1/evaluations/runs/{run_id}`

평가 상태, configuration snapshot, Git SHA, aggregate metrics, report artifact 위치를 반환한다.

## 9. Pagination

목록 API는 cursor pagination을 사용한다.

```json
{
  "items": [],
  "next_cursor": "opaque-or-null"
}
```

## 10. Contract Test Requirements

- OpenAPI schema snapshot test
- Pydantic request/response serialization test
- MCP tool schema와 내부 use case schema 호환성 test
- 실제 page range를 벗어난 요청 test
- abstention이 HTTP error로 변환되지 않는지 test
- stale version과 index mismatch error test

## 11. 관련 문서

- [Requirements](./requirements.md)
- [Data Model](./data-model.md)
- [Agent & MCP Design](./agent-mcp-design.md)

