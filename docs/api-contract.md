# API Contract

## 1. 현재 범위

FastAPI는 매니페스트에 고정된 AI 보안 PDF 6개를 검증하고 하나의 메모리 인덱스에서 검색합니다. 문서 업로드, 목록, 비동기 ingestion job과 평가 API는 아직 없습니다. `/docs`의 OpenAPI 화면을 현재 계약의 최종 기준으로 사용합니다.

## 2. Endpoints

| Method | Path | 역할 |
| --- | --- | --- |
| `GET` | `/health/live` | 프로세스 liveness 확인 |
| `GET` | `/v1/documents/{document_id}/pdf` | Citation 링크용 로컬 PDF 반환 |
| `POST` | `/v1/search` | 선택한 검색 모드로 Chunk 검색 |
| `POST` | `/v1/answers` | Rerank Evidence 기반 추출형 답변 또는 보류 |
| `POST` | `/v1/agent/answers` | 제한된 재검색과 trace를 포함한 Agent 답변 |

## 3. Search

### `POST /v1/search`

```json
{
  "query": "프롬프트 인젝션 완화 방법",
  "mode": "rerank",
  "top_k": 5
}
```

`mode`는 `bm25`, `dense`, `hybrid`, `rerank` 중 하나입니다. `top_k`는 1~20입니다.

```json
{
  "query_id": "uuid",
  "document_id": "configured-document-id",
  "mode": "rerank",
  "embedding_model": null,
  "reranker_model": "jinaai/jina-reranker-v2-base-multilingual",
  "results": [
    {
      "rank": 1,
      "document_id": "kisa-ai-red-teaming-guide-2026",
      "document_title": "AI 보안 레드티밍 가이드",
      "publisher": "KISA",
      "language": "ko-KR",
      "document_version": "2026",
      "chunk_id": "uuid",
      "version_id": "uuid",
      "page_start": 12,
      "page_end": 12,
      "text": "source text",
      "score": 0.82
    }
  ],
  "latency_ms": 123.4
}
```

## 4. Grounded Answer

### `POST /v1/answers`

```json
{
  "question": "프롬프트 인젝션 완화 방법은?",
  "top_k": 5,
  "max_claims": 2
}
```

- `top_k`: 1~10
- `max_claims`: 1~3
- 검색 모드는 항상 `rerank`입니다.
- 답변은 외부 LLM이 아닌 Evidence 원문 발췌입니다.

성공 응답의 핵심 필드:

```json
{
  "answer": "- 검증된 원문 문장 (문서명, p.12)",
  "abstained": false,
  "claims": [],
  "citations": [
    {
      "document_id": "kisa-ai-red-teaming-guide-2026",
      "document_title": "AI 보안 레드티밍 가이드",
      "page_number": 12,
      "quote": "검증된 원문 문장"
    }
  ],
  "evidence_count": 5,
  "sufficiency": "SUFFICIENT",
  "termination_reason": "ANSWER_VALIDATED",
  "latency_ms": 456.7
}
```

근거 부족은 오류가 아닌 `200 OK`입니다.

```json
{
  "answer": null,
  "abstained": true,
  "claims": [],
  "citations": [],
  "sufficiency": "INSUFFICIENT",
  "termination_reason": "EVIDENCE_INSUFFICIENT"
}
```

## 5. Agent Answer

### `POST /v1/agent/answers`

```json
{
  "question": "AI 레드티밍 절차는?",
  "top_k": 5,
  "max_claims": 2,
  "max_retrieval_attempts": 2,
  "max_steps": 14,
  "tool_timeout_seconds": 45.0,
  "max_repair_attempts": 1
}
```

응답은 Grounded Answer에 다음 실행 정보를 더합니다.

- `trace_id`
- `question_class`
- `step_count`, `retrieval_attempts`, `repair_attempts`
- `search_queries`, `search_modes`
- `tool_errors`
- `termination_reason`
- 순서가 있는 `trace`

종료 이유는 `ANSWER_VALIDATED`, `RETRIEVAL_LIMIT_REACHED`, `ANSWER_VALIDATION_FAILED`, `PROMPT_INJECTION_DETECTED`, `STEP_LIMIT_REACHED`, `TOOL_ERROR`, `TOOL_TIMEOUT` 중 하나입니다.

## 6. PDF

### `GET /v1/documents/{document_id}/pdf`

매니페스트의 source ID를 `document_id`로 사용해 해당 로컬 PDF를 브라우저 inline 응답으로 반환합니다. UI는 `#page=N` fragment를 붙여 Citation 페이지를 엽니다. 알 수 없는 ID로 임의 파일 경로를 조회할 수 없습니다.

## 7. 오류

- 요청 schema 오류: FastAPI `422`
- 알 수 없는 문서 ID 또는 없는 PDF: `404`
- 설정된 PDF 파싱 실패: 검색 서비스 준비 시 `503`
- 근거 부족: `200` + `abstained=true`
- Agent tool timeout·오류: 가능한 경우 구조화된 Agent 종료 응답

내부 exception 원문이나 로컬 경로를 공개 응답에 추가하지 않습니다.
