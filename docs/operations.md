# Operations Guide

## 1. 운영 범위

로컬 개발, CI, 포트폴리오 데모 환경에서 동일한 서비스 구성과 환경변수 계약을 사용한다. 대규모 production 운영은 MVP 범위가 아니지만 장애를 재현하고 진단할 수 있는 최소 관측성을 갖춘다.

## 2. Services

| Service | 기본 Port | 역할 |
| --- | ---: | --- |
| API | 8000 | REST API와 health endpoint |
| Streamlit | 8501 | 데모 UI |
| PostgreSQL | 5432 | metadata source of truth |
| Qdrant | 6333 | Dense Vector Search |
| OpenSearch | 9200 | BM25 Search |
| MinIO | 9000/9001 | 원본·artifact storage |
| Langfuse | 배포별 설정 | trace와 LLM 관측성 |

Port는 local 기본값이며 환경변수로 변경한다.

## 3. Environment Variables

### Application

```text
APP_ENV
APP_LOG_LEVEL
APP_HOST
APP_PORT
APP_CORS_ORIGINS
```

### Database & Storage

```text
DATABASE_URL
QDRANT_URL
QDRANT_API_KEY
OPENSEARCH_URL
OPENSEARCH_USERNAME
OPENSEARCH_PASSWORD
S3_ENDPOINT_URL
S3_ACCESS_KEY
S3_SECRET_KEY
S3_BUCKET
```

### Models

```text
OPENAI_API_KEY
OPENAI_CHAT_MODEL
EMBEDDING_MODEL
RERANKER_MODEL
MODEL_CACHE_DIR
```

### Observability

```text
LANGFUSE_HOST
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
OTEL_EXPORTER_OTLP_ENDPOINT
```

### Limits

```text
MAX_UPLOAD_SIZE_MB
MAX_PDF_PAGES
AGENT_MAX_STEPS
AGENT_TIMEOUT_SECONDS
RETRIEVAL_TIMEOUT_SECONDS
LLM_TIMEOUT_SECONDS
```

`.env.example`에는 실제 secret을 포함하지 않는다.

## 4. Configuration Precedence

```text
code defaults
  < config YAML
  < environment variables
  < explicit CLI arguments
```

평가 run은 최종 merge된 configuration snapshot을 artifact에 저장한다.

## 5. Health Endpoints

### `/health/live`

프로세스가 요청을 받을 수 있는지만 확인한다. 외부 dependency를 호출하지 않는다.

### `/health/ready`

다음을 짧은 timeout으로 확인한다.

- PostgreSQL connection
- 활성 Qdrant collection
- OpenSearch active alias
- S3/MinIO bucket access
- migration version

LLM provider 장애는 API 전체 readiness를 내리지 않고 dependency 상태로 별도 노출할 수 있다.

### `/health/dependencies`

관리·debug용으로 각 dependency latency와 상태를 반환한다. secret이나 내부 URL 전체를 노출하지 않는다.

## 6. Logging

구조화 JSON 로그 필드:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "service": "api",
  "environment": "local",
  "request_id": "...",
  "trace_id": "...",
  "document_id": "...",
  "job_id": "...",
  "event": "retrieval.completed",
  "duration_ms": 410,
  "status": "success"
}
```

- stack trace는 server log에만 남기고 API 응답에 노출하지 않는다.
- 질문·문서 원문은 기본 로그에서 제외한다.
- error에는 typed error code와 dependency만 기록한다.

## 7. Metrics

### API

- request count/error count
- latency p50/p95/p99
- active requests
- upload size

### Ingestion

- job success/failure
- page parse latency
- OCR page ratio
- Chunk count
- index failure/retry count

### Retrieval

- backend별 latency/error
- candidate count
- reranker latency
- sufficiency 상태 분포
- fallback 사용 비율

### Agent

- total steps
- tool call count
- retrieval attempts
- abstention rate
- termination reason
- token usage/cost

## 8. Tracing

하나의 answer 요청에 다음 span을 연결한다.

```text
answer.request
├── agent.classify
├── retrieval.hybrid
│   ├── qdrant.search
│   ├── opensearch.search
│   └── reranker.predict
├── document.get_page
├── llm.generate_answer
└── citation.validate
```

Trace에는 모델명, prompt version, tool version, token, latency를 남기고 원문 전체는 남기지 않는다.

## 9. Docker Compose Startup

권장 순서:

```text
1. PostgreSQL, Qdrant, OpenSearch, MinIO
2. migrations
3. API와 worker
4. MCP servers
5. Streamlit
6. smoke tests
```

서비스 시작 후 readiness를 확인하고 index/alias가 없으면 bootstrap command를 실행한다.

## 10. Deployment Checklist

- [ ] 모든 image가 immutable tag 또는 Git SHA를 사용한다.
- [ ] migration backup과 rollback 절차가 있다.
- [ ] 환경변수와 secret이 설정되었다.
- [ ] bucket, collection, index alias가 준비되었다.
- [ ] readiness가 통과한다.
- [ ] 샘플 ingestion smoke test가 통과한다.
- [ ] 검색과 Citation page link가 동작한다.
- [ ] 평가 MVP gate가 통과한다.
- [ ] 로그에 secret·원문 전체가 노출되지 않는다.
- [ ] rollback 대상 release가 확인된다.

## 11. Backup & Recovery

| 대상 | 전략 |
| --- | --- |
| PostgreSQL | 정기 dump/snapshot, migration 전 backup |
| Original PDF | versioned object storage 또는 별도 backup |
| Qdrant | 재생성 가능, 필요 시 snapshot |
| OpenSearch | 재생성 가능, 필요 시 snapshot |
| Evaluation reports | release artifact로 보존 |

PostgreSQL과 원본 PDF가 있으면 검색 인덱스를 재생성할 수 있어야 한다.

## 12. Runbooks

### 12.1 Document stuck in `PARSING`

1. job heartbeat와 worker 상태 확인
2. 마지막 checkpoint와 실패 page 확인
3. 동일 idempotency key의 중복 worker 확인
4. 안전한 경우 job을 retry queue로 이동
5. 반복 실패 page를 regression fixture로 추가

### 12.2 Qdrant unavailable

1. readiness와 network 확인
2. application이 BM25 fallback을 사용했는지 확인
3. collection/index version 확인
4. 복구 후 Dense smoke query 실행
5. 필요하면 DB Chunk에서 재색인

### 12.3 OpenSearch unavailable

1. cluster health와 disk 상태 확인
2. application이 Dense fallback을 사용했는지 확인
3. alias와 mapping version 확인
4. 복구 후 exact code query smoke test

### 12.4 Wrong citation page

1. Citation의 version/page/chunk ID 확인
2. DB Chunk의 Element와 Page mapping 확인
3. 활성 index version mismatch 확인
4. parser의 0/1-based 변환 여부 확인
5. 영향을 받은 문서를 재색인하고 regression test 추가

### 12.5 Agent loop or timeout

1. trace의 node와 tool call count 확인
2. max step/retrieval limit 적용 여부 확인
3. 동일 query rewrite 반복 여부 확인
4. dependency timeout 확인
5. 종료 정책 test 추가

## 13. Release & Rollback

Release:

1. full CI와 evaluation 실행
2. release image build
3. migration dry run
4. staging smoke test
5. 배포 후 health와 핵심 질문 검증
6. `v0.1.0` tag와 report 연결

Rollback:

- application image를 이전 SHA로 되돌린다.
- destructive migration은 사용하지 않고 backward-compatible migration을 우선한다.
- 검색 index는 이전 alias로 전환한다.
- 문서 active version을 이전 안정 version으로 되돌린다.

## 14. 관련 문서

- [Data Policy](./data-policy.md)
- [Testing Strategy](./testing-strategy.md)
- [Evaluation Plan](./evaluation-plan.md)

