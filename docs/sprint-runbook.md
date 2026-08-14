# 14-Day Sprint Runbook

## 1. 사용 방법

이 문서는 [Development Plan](./development-plan.md)의 압축 일정을 실제 일일 작업으로 변환한다. Day 1~8에 기능 완성본을 만들고 Day 9~14에 실패 사례와 품질을 개선한다.

매일 다음 순서를 따른다.

```text
오늘 Gate 확인
  → 관련 설계 문서 읽기
  → 가장 작은 Vertical Slice 구현
  → 자동 테스트와 평가 실행
  → 결과와 알려진 실패 기록
  → 동작하는 commit으로 종료
```

## 2. 공통 일일 체크리스트

- [ ] 오늘 작업 범위와 제외 범위를 issue에 기록했다.
- [ ] 관련 요구사항 ID를 확인했다.
- [ ] 구현 전 실패하는 test 또는 evaluation case를 만들었다.
- [ ] 설정값과 모델 version을 기록했다.
- [ ] secret·비공개 PDF가 Git status에 없는지 확인했다.
- [ ] lint, type check, 관련 test를 실행했다.
- [ ] 성능이나 품질 변화가 있으면 baseline과 비교했다.
- [ ] 알려진 실패와 다음 작업을 기록했다.
- [ ] 하나 이상의 동작하는 commit으로 종료했다.

## 3. Core Build

### Day 1 — 요구사항, 데이터 계약, 프로젝트 기반

#### 읽을 문서

- [Requirements](./requirements.md)
- [Data Model](./data-model.md)
- [Architecture](./architecture.md)
- [Data Policy](./data-policy.md)

#### 작업

- [ ] MVP 포함·제외 범위와 Open Questions를 확정한다.
- [ ] FR/NFR/AC ID를 검토하고 모순을 제거한다.
- [ ] Document, DocumentVersion, Page, Element, Table, Chunk, Citation Pydantic model을 만든다.
- [ ] Python 3.11+, `uv`, `src` layout을 구성한다.
- [ ] FastAPI `/health/live` endpoint를 만든다.
- [ ] Ruff, mypy, pytest를 구성한다.
- [ ] Docker Compose에 PostgreSQL, Qdrant, OpenSearch, MinIO를 정의한다.
- [ ] CI에서 format, lint, type, unit test를 실행한다.
- [ ] `data/samples/manifest.yaml` schema를 만든다.
- [ ] 재배포 가능한 샘플 PDF와 평가 질문 초안을 준비한다.

#### 필수 산출물

```text
pyproject.toml
uv.lock
.env.example
docker-compose.yml
src/semiconductor_rag/domain/
apps/api/
tests/unit/
data/samples/manifest.yaml
data/eval/questions.jsonl
.github/workflows/ci.yml
```

#### Day 1 Gate

- [ ] clean environment에서 dependency 설치가 된다.
- [ ] `/health/live`가 200을 반환한다.
- [ ] Domain model unit test가 통과한다.
- [ ] Docker dependency가 시작되고 readiness를 확인한다.
- [ ] 최소 샘플 문서 5개와 질문 30개가 준비된다.
- [ ] secret·라이선스 미확인 문서가 Git에 없다.

### Day 2 — PDF, OCR, 표, Chunking

#### 읽을 문서

- [Ingestion Design](./ingestion-design.md)
- [ADR-0001](./adr/0001-page-centric-evidence-model.md)
- [ADR-0003](./adr/0003-document-parser-stack.md)

#### 작업

- [ ] 업로드 검증과 SHA-256 fingerprint를 구현한다.
- [ ] PyMuPDF 기반 Page inspection과 렌더링을 구현한다.
- [ ] Docling adapter와 공통 Element 변환을 구현한다.
- [ ] OCR 필요 페이지 판정과 PaddleOCR adapter를 구현한다.
- [ ] OCR/native text 중복 병합을 구현한다.
- [ ] 표 JSON·Markdown 직렬화를 구현한다.
- [ ] section/page-aware Chunker를 구현한다.
- [ ] PostgreSQL persistence와 ingestion status를 구현한다.
- [ ] parser quality report를 생성한다.
- [ ] text, scan, table fixture test를 작성한다.

#### Day 2 Gate

- [ ] 모든 Chunk가 DocumentVersion과 PDF 페이지로 역추적된다.
- [ ] text PDF, scan PDF, table PDF fixture가 처리된다.
- [ ] 동일 PDF 재처리가 중복 version/index를 만들지 않는다.
- [ ] 파싱 실패 페이지가 전체 job을 중단하지 않는다.
- [ ] DB Chunk 수와 quality report가 일치한다.

### Day 3 — Dense, BM25, Hybrid Retrieval

#### 읽을 문서

- [Retrieval Design](./retrieval-design.md)
- [ADR-0002](./adr/0002-hybrid-retrieval.md)
- [Evaluation Plan](./evaluation-plan.md)

#### 작업

- [ ] embedding adapter와 model version 기록을 구현한다.
- [ ] Qdrant collection, payload, filter를 구현한다.
- [ ] OpenSearch mapping과 BM25 query를 구현한다.
- [ ] 문서 단위 replace indexing을 구현한다.
- [ ] Dense/BM25 병렬 검색을 구현한다.
- [ ] RRF와 deterministic tie breaking을 구현한다.
- [ ] 후보 중복 제거와 문서 diversity를 구현한다.
- [ ] `/v1/search` endpoint를 구현한다.
- [ ] Qdrant/OpenSearch 장애 fallback을 구현한다.
- [ ] R1 Dense, R2 BM25, R3 Hybrid baseline을 실행한다.

#### Day 3 Gate

- [ ] 동일 질문에 Dense, BM25, Hybrid 결과를 비교할 수 있다.
- [ ] exact 장비 코드와 의미 질문이 모두 평가된다.
- [ ] 검색 결과에서 원문 페이지로 이동할 수 있다.
- [ ] 한 backend 장애 시 degraded 검색이 동작한다.
- [ ] baseline Recall@5, MRR, latency가 저장된다.

### Day 4 — Reranking, Domain Search, Answer, Citation

#### 읽을 문서

- [Retrieval Design](./retrieval-design.md)
- [API Contract](./api-contract.md)
- [Evaluation Plan](./evaluation-plan.md)

#### 작업

- [ ] Cross-Encoder Reranker를 구현한다.
- [ ] 반도체 약어·한영 glossary schema와 loader를 구현한다.
- [ ] Query Expansion과 trace를 구현한다.
- [ ] Evidence Pack builder를 구현한다.
- [ ] atomic Claim과 Citation schema를 구현한다.
- [ ] Evidence-only answer prompt를 구현한다.
- [ ] Citation page/quote/version 검증을 구현한다.
- [ ] 근거 충분성 상태와 답변 보류를 구현한다.
- [ ] 다중 문서 comparison grouping을 구현한다.
- [ ] 표 질문 answer path를 구현한다.
- [ ] R4 Expansion, R5 Reranker 평가를 실행한다.

#### Day 4 Gate

- [ ] R1~R5 검색 비교 결과가 있다.
- [ ] 단일 문서, 비교, 표 질문이 페이지 Citation과 함께 동작한다.
- [ ] 답변 불가능 질문이 추측 없이 보류된다.
- [ ] Citation quote가 해당 PDF 페이지에서 검증된다.
- [ ] 검색·Citation MVP Gate의 현재 값과 부족한 항목이 기록된다.

### Day 5 — Minimal Agentic RAG

#### 읽을 문서

- [Agent & Tool Design](./agent-mcp-design.md)
- [ADR-0005](./adr/0005-langgraph-orchestration.md)
- [ADR-0006](./adr/0006-in-process-agent-tools.md)

#### 작업

- [x] LangGraph `AgentState`와 조건부 routing을 구현한다.
- [x] 검색과 답변 기능을 typed in-process tool로 연결한다.
- [x] 첫 검색에는 BM25, 재검색에는 Query Rewrite와 Reranker를 적용한다.
- [x] 최대 검색 횟수와 종료 이유를 적용한다.
- [x] Citation 검증 실패를 최종 답변에서 차단한다.
- [x] `/v1/agent/answers`와 재구성 가능한 trace를 제공한다.
- [x] 첫 검색 성공, 재검색 성공, 보류, Citation 실패 경로를 테스트한다.

#### Day 5 Gate

- [x] Agent가 검색 결과에 따라 답변, 재검색 또는 보류를 선택한다.
- [x] 무한 재검색이 최대 횟수로 차단된다.
- [x] 잘못된 input이 schema error로 반환된다.
- [x] 원문과 다른 Citation이 최종 답변에서 제거된다.
- [x] trace로 검색어, 검색 모드와 종료 이유를 재구성할 수 있다.

### Day 6 — LangGraph Agent

#### 읽을 문서

- [Agent & MCP Design](./agent-mcp-design.md)
- [ADR-0005](./adr/0005-langgraph-orchestration.md)

#### 작업

- [x] AgentState를 구현한다.
- [x] classify, plan, retrieve, rewrite, gather node를 구현한다.
- [x] generate, validate, repair, abstain, finalize node를 구현한다.
- [x] routing 조건과 종료 이유 enum을 구현한다.
- [x] step/retrieval/tool error/timeout limit을 적용한다.
- [x] 합의한 MVP 범위에 따라 MCP 대신 typed in-process tool 경계를 유지한다.
- [x] `/v1/agent/answers` endpoint에 실행 제한과 복구 trace를 연결한다.
- [x] prompt injection 방어 규칙을 적용한다.
- [x] 주요 edge와 termination path test를 작성한다.

#### Day 6 Gate

- [x] 첫 검색 성공, 재검색 성공과 보류 경로가 통과한다.
- [ ] 표 검색과 다중 문서 비교 경로는 후속 데이터 확장 범위로 남긴다.
- [x] step·검색·복구 횟수 제한으로 무한 loop가 불가능하다.
- [x] tool 오류 후 retry/fallback/abstention이 동작한다.
- [x] invalid Citation과 인용으로 뒷받침되지 않는 Claim이 최종 답변에 남지 않는다.
- [x] trace로 node와 tool 경로를 재구성할 수 있다.

### Day 7 — 자동 평가와 관측성

#### 읽을 문서

- [Evaluation Plan](./evaluation-plan.md)
- [Testing Strategy](./testing-strategy.md)
- [Operations](./operations.md)

#### 작업

- [x] evaluation dataset validator를 구현한다.
- [x] Recall@K, Precision@K, Page Hit@K, MRR, nDCG@K를 구현한다.
- [x] answer fact coverage와 numeric accuracy를 구현한다.
- [x] Citation precision·coverage·page·quote metrics를 구현한다.
- [x] abstention precision·recall과 unsafe answer rate를 구현한다.
- [x] Agent trajectory·termination·retry metrics를 구현한다.
- [x] evaluation manifest와 report generator를 구현한다.
- [x] 개인정보를 기록하지 않는 구조화 JSONL 실행 로그를 연결한다.
- [x] 비용·token·latency budget을 manifest에 기록한다.
- [x] full evaluation run을 실행한다.

Langfuse 연동은 외부 서비스 운영이 필요한 범위이므로 MVP에서 제외했다. 대신 같은 실행을 재현하고 실패 단계를 확인하는 데 필요한 이벤트, 소요 시간, 상태를 `events.jsonl`에 기록한다.

#### Day 7 Gate

- [x] 한 명령으로 전체 evaluation report가 생성된다.
- [x] Git SHA와 모델·설정 version이 report에 포함된다.
- [x] 질문 유형과 언어별 slice metric을 확인할 수 있다.
- [x] 실패 사례가 `failures.md`에 자동 정리된다.
- [x] MVP Gate 통과 여부와 미달 항목이 명확하다.

### Day 8 — UI, 배포, Demo, v0.1.0

#### 읽을 문서

- [API Contract](./api-contract.md)
- [Operations](./operations.md)
- [Data Policy](./data-policy.md)

#### 작업

- [x] 고정된 로컬 PDF를 대상으로 질문·검색 설정 UI를 만든다.
- [x] 일반 RAG와 Agentic RAG 선택 UI를 만든다.
- [x] 답변 Claim과 Citation을 연결해 표시한다.
- [x] Citation에서 브라우저 원문 PDF 페이지를 열 수 있게 한다.
- [x] 답변 보류와 API 오류 상태를 표시한다.
- [x] Agent 검색 방식과 실행 trace를 표시한다.
- [ ] 전체 Docker Compose 실행을 검증한다.
- [ ] 배포 환경과 secret을 설정한다.
- [x] 실제 FastAPI와 Streamlit을 연결한 smoke test를 실행한다.
- [x] README에 로컬 실행법을 반영한다.
- [ ] 데모 영상/GIF와 `v0.1.0` release note를 준비한다.

문서 업로드 관리, Docker Compose, 외부 배포와 `v0.1.0` 공개는 미니 프로젝트의 Day 8 범위에서 제외한다. 고정된 공개 가능 PDF 한 개를 질문하고 Citation 페이지를 확인하는 데모에 집중하며, 성능 Gate를 개선한 뒤 릴리스를 준비한다.

#### Day 8 Gate

- [x] 현재 로컬 환경에서 문서화된 명령으로 실행된다.
- [x] 사용자가 ask → answer → citation page 확인을 완료할 수 있다.
- [x] UI와 로그에 비공개 문서 내용·secret이 추가되지 않는다.
- [ ] evaluation report와 알려진 제한이 공개된다.
- [ ] rollback 대상 image/index/version이 확인된다.

## 4. Hardening

### Day 9 — Retrieval Error Analysis

- [ ] 실패 질문을 `missed`, `low_rank`, `wrong_document`, `wrong_page`, `table_miss`, `expansion_error`로 분류한다.
- [ ] Dense/BM25 후보 단계와 Reranker 단계를 분리해 원인을 찾는다.
- [ ] threshold와 top-k를 validation split에서만 조정한다.
- [ ] holdout 결과를 확인하고 과적합 여부를 기록한다.
- Gate: 주요 retrieval failure 유형마다 최소 하나의 regression case가 있다.

### Day 10 — PDF, OCR, Table Edge Cases

- [ ] 파싱 실패 문서를 fixture로 축소한다.
- [ ] 회전, 2단, 반복 header/footer, 다중 페이지 표를 검증한다.
- [ ] OCR confidence와 핵심 단위·수치 보존을 측정한다.
- [ ] parser 변경이 기존 golden fixture를 깨지 않는지 확인한다.
- Gate: 새 parser fix마다 fixture와 quality metric이 있다.

### Day 11 — Citation & Abstention Hardening

- [ ] wrong page, stale version, quote mismatch를 집중 검증한다.
- [ ] unsupported Claim이 repair 또는 제거되는지 확인한다.
- [ ] 답변 가능·불가능 threshold를 validation split에서 조정한다.
- [ ] false abstention과 unsafe answer를 함께 줄인다.
- Gate: Citation Gate와 Unsafe Answer Rate Gate를 통과한다.

### Day 12 — Agent & MCP Reliability

- [ ] MCP timeout, invalid schema, partial backend failure를 주입한다.
- [ ] 중복 Query Rewrite와 불필요한 Tool Call을 줄인다.
- [ ] max step과 timeout 직전 종료 응답을 확인한다.
- [ ] trajectory metric과 평균 비용을 비교한다.
- Gate: 필수 trajectory case와 오류 복구 case가 모두 통과한다.

### Day 13 — Performance, Deployment, Documentation

- [ ] search/answer p95 latency를 측정한다.
- [ ] cold start와 model cache 문제를 확인한다.
- [ ] clean Docker startup과 migration/alias bootstrap을 검증한다.
- [ ] Data Policy publication checklist를 실행한다.
- [ ] 문서의 명령·링크·환경변수를 다시 검증한다.
- Gate: 다른 환경에서 README만 보고 데모를 실행할 수 있다.

### Day 14 — Final Release Approval

- [ ] holdout을 포함한 final evaluation을 다시 실행한다.
- [ ] 모든 Release Gate를 확인한다.
- [ ] critical/high defect가 없는지 확인한다.
- [ ] README Architecture, Demo, Metrics, Limitations를 최종 갱신한다.
- [ ] `v0.1.0` tag와 evaluation report를 연결한다.
- [ ] 최종 데모 시나리오를 녹화한다.
- Gate: 저장소 clone부터 최종 Citation 확인까지 전체 재현에 성공한다.

## 5. Scope Cut Rules

일정이 밀리면 다음 순서로 범위를 줄인다.

1. 제조 데이터 SQL·Pandas 확장
2. 외부 공개 배포와 production 관측성
3. 복잡한 다중 페이지 표 병합
4. 다양한 모델 Provider 지원
5. 고급 UI 시각화

다음 항목은 줄이지 않는다.

- PDF 페이지 추적
- Hybrid Retrieval baseline 비교
- Citation 검증
- 답변 보류
- 평가 데이터와 결과
- Agent 종료 한도

## 6. Daily Report Template

```markdown
# Day N Report

## 목표

## 완료

## 테스트·평가 결과

| 항목 | 이전 | 현재 | 변화 |
| --- | ---: | ---: | ---: |

## 실패 사례

## 기술 결정

## 알려진 문제

## 다음 Day 시작점
```

