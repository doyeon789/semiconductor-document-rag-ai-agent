# Development Plan

## 1. 목표

반도체 PDF, 공정 문서, 장비 매뉴얼, 논문을 대상으로 다음 흐름을 단계적으로 구현한다.

```text
문서 처리
  → 페이지 기반 검색
  → Hybrid Search 및 Reranking
  → 근거 기반 답변과 인용 검증
  → LangGraph Agent와 MCP 도구 연동
  → 자동 평가, UI, 배포
```

핵심 원칙은 **Agent를 먼저 구현하지 않고 검색과 인용 품질을 먼저 확보하는 것**이다.

## 2. 단계별 개발 계획

### Phase 0. 요구사항 및 성공 기준 확정

#### 주요 작업

- 지원 문서 범위 정의
  - 텍스트 PDF
  - 스캔 PDF
  - 논문
  - 장비 매뉴얼
- 지원 언어 정의
  - 한국어
  - 영어
  - 한영 혼합 질문
- 핵심 질문 유형 정의
  - 단일 문서 검색
  - 다중 문서 비교
  - 표 데이터 조회
  - 문서 요약
  - 답변 불가능 질문
- 답변 출력 형식 정의
  - 최종 답변
  - 문서명
  - 페이지 번호
  - 근거 문장
  - 답변 보류 사유
- 기능 및 성능 Acceptance Criteria 작성
- 문서 저작권과 샘플 데이터 정책 작성

#### 산출물

```text
docs/
├── requirements.md
├── architecture.md
├── data-policy.md
├── evaluation-plan.md
└── adr/
```

#### 완료 조건

- MVP 포함 범위와 제외 범위가 명확하다.
- 주요 질문 유형마다 기대 입력과 출력 예시가 있다.
- 검색, 인용, 답변 보류 기능을 수치로 평가할 기준이 있다.

### Phase 1. 프로젝트 기반 구성

#### 주요 작업

- Python 3.11+ 및 `uv` 기반 프로젝트 생성
- `src` layout과 테스트 디렉터리 구성
- 환경변수 및 설정 관리
- Ruff, mypy, pytest 설정
- GitHub Actions 기반 CI 구성
- Docker Compose 개발 환경 구성
- 로깅 및 공통 예외 처리 정의

#### 완료 조건

- 신규 환경에서 동일한 명령으로 의존성을 설치할 수 있다.
- lint, type check, unit test가 CI에서 실행된다.
- 빈 FastAPI 애플리케이션의 health check가 통과한다.

### Phase 2. 문서 처리 MVP

#### 첫 번째 Vertical Slice

> PDF 한 개를 업로드하고 페이지 정보를 유지한 상태로 파싱한 뒤, 질문과 관련된 페이지를 검색한다.

#### 주요 작업

- `Document`, `Page`, `Chunk`, `Citation` 데이터 모델 정의
- PyMuPDF 또는 Docling 기반 텍스트 PDF 파싱
- 페이지 번호 및 문서 메타데이터 보존
- 기본 Chunking 전략 구현
- 파싱 결과 저장 형식 정의
- 스캔 문서 OCR fallback 구현
- 표 및 레이아웃 파싱 확장
- 단위 테스트용 재배포 가능 샘플 PDF 준비

#### 핵심 메타데이터

```text
document_id
document_title
page_number
section
chunk_id
content_type
bbox
source_path
```

#### 완료 조건

- 모든 Chunk가 원본 문서와 페이지로 역추적된다.
- 동일 문서를 다시 처리해도 중복 데이터가 생성되지 않는다.
- 텍스트 PDF 파싱 결과를 fixture 기반 테스트로 검증한다.

### Phase 3. 검색 Baseline 및 품질 개선

#### 구현 순서

1. Dense Vector Search
2. BM25 Keyword Search
3. Hybrid Search 결과 융합
4. Cross-Encoder Reranking
5. 반도체 약어·한영 용어 사전
6. Query Expansion
7. 페이지 수준 검색 평가

#### 평가 지표

- Recall@K
- Precision@K
- MRR
- nDCG@K
- Page Hit Rate

#### 완료 조건

- 평가 질문마다 정답 페이지가 정의되어 있다.
- Dense, BM25, Hybrid, Hybrid+Reranker 결과를 동일 데이터셋으로 비교한다.
- 검색 설정과 평가 결과가 재현 가능하게 저장된다.

### Phase 4. 근거 기반 답변과 인용 검증

#### 주요 작업

- 검색된 문맥만 사용하는 답변 생성
- 문서명과 페이지 번호 표시
- 주장과 근거 Chunk 연결
- 원문 페이지 확인 경로 제공
- 상충하는 문서 탐지
- 근거 부족 시 답변 보류
- 인용 페이지와 실제 근거 일치 여부 검증

#### 평가 지표

- Faithfulness
- Answer Relevancy
- Citation Precision
- Citation Coverage
- Page Match Accuracy
- Abstention Precision / Recall

#### 완료 조건

- 답변의 핵심 주장마다 하나 이상의 검증 가능한 인용이 있다.
- 근거가 없는 질문에 임의로 답변하지 않는다.
- 잘못된 페이지 인용을 자동 평가할 수 있다.

### Phase 5. LangGraph Agent 및 MCP

#### MCP 서버

- Retrieval MCP Server
  - 검색
  - Hybrid Fusion
  - Reranking
- Document MCP Server
  - 원문 페이지 조회
  - 표 조회
  - 문서 메타데이터 조회
- Citation MCP Server
  - 주장-근거 검증
  - 인용 유효성 확인

#### LangGraph 흐름

```text
질문 분석
  → 도구 선택
  → 검색
  → 근거 충분성 판단
  → Query Rewrite 또는 추가 도구 호출
  → 답변 생성
  → 인용 검증
  → 최종 답변 또는 답변 보류
```

#### 완료 조건

- 각 MCP 도구를 Agent 없이 독립적으로 테스트할 수 있다.
- 도구 선택과 재검색 조건이 명시적인 상태 전이로 정의되어 있다.
- 최대 재시도 횟수와 종료 조건이 설정되어 있다.
- Tool Selection Accuracy와 Retry Success Rate를 평가한다.

### Phase 6. UI, 운영 및 배포

#### 주요 작업

- Streamlit 기반 데모 UI
- 검색 결과 및 원문 페이지 표시
- 답변과 인용 근거 연결 표시
- Langfuse 기반 trace와 latency 관찰
- Docker 기반 실행 환경
- 운영 오류 및 비용 모니터링
- 배포 문서 작성

#### 완료 조건

- 사용자가 문서를 등록하고 질문한 뒤 원문 근거까지 확인할 수 있다.
- 주요 실패 단계가 trace에 기록된다.
- 신규 환경에서 문서화된 절차로 실행할 수 있다.

### Phase 7. 제조 데이터 분석 확장

핵심 RAG가 완성된 후 SQL·Pandas 기반 제조 데이터 분석 기능을 추가한다.

- 공정 데이터 조회
- 조건별 통계 분석
- 문서 근거와 제조 데이터 분석 결과의 결합

## 3. 구현 전 확정할 기술 결정

결정 내용과 이유는 `docs/adr/`에 기록한다.

- Docling, PyMuPDF, PaddleOCR의 역할과 fallback 순서
- 페이지, 섹션, 문단, 표 단위 Chunking 정책
- Embedding 및 Reranker 모델
- Qdrant와 OpenSearch의 운영 범위
- LLM 및 API Provider
- 로컬·배포 환경과 GPU 사용 가능 여부
- PostgreSQL 및 Object Storage 스키마
- 원본 PDF 저장과 접근 권한 정책

## 4. 14-Day Intensive Sprint

핵심 기능은 8일 안에 완성하고, 남은 6일은 검색·인용·Agent 품질을 높이고 최종 릴리스를 안정화하는 데 사용한다.

### Core Build: Day 1-8

| Day | 통합 범위 | 주요 작업 | 종료 조건 |
| ---: | --- | --- | --- |
| 1 | 기존 Day 1+2 | 요구사항, Acceptance Criteria, ADR, 프로젝트 구조, CI, 데이터 스키마, 샘플 문서와 평가 질문 | FastAPI health check와 CI가 통과하고 샘플 문서·평가 질문이 준비된다. |
| 2 | 기존 Day 3+4 | PDF 파서, 페이지 추적, Chunking, OCR fallback, 표·레이아웃 처리 | 텍스트·스캔·표 샘플을 처리하고 모든 Chunk를 원문 페이지로 역추적한다. |
| 3 | 기존 Day 5+6 | Embedding, Qdrant, Dense Search, OpenSearch BM25, Hybrid Fusion | Dense, BM25, Hybrid 검색을 동일 API와 데이터셋으로 비교할 수 있다. |
| 4 | 기존 Day 7+8+9 | Reranker, 반도체 용어 확장, 검색 평가, Grounded Answer, 페이지 인용, 다중 문서 비교, 표 검색, 답변 보류 | 검색 지표가 생성되고 비교·표·답변 불가 시나리오가 페이지 인용과 함께 동작한다. |
| 5 | 기존 Day 10 | Retrieval·Document·Citation MCP Server | 각 MCP 도구가 독립적으로 호출되고 통합 테스트를 통과한다. |
| 6 | 기존 Day 11 | LangGraph Agent, Function Calling, Query Rewrite, 재검색 | 도구 선택부터 최종 답변 또는 답변 보류까지 Agent 흐름이 완주한다. |
| 7 | 기존 Day 12 | 자동 평가, Langfuse, 회귀 테스트, 운영 지표 | 검색·답변·인용·Agent 평가 리포트와 trace가 생성된다. |
| 8 | 기존 Day 13+14 | Streamlit UI, Docker, 배포, 버그 수정, 데모, README, `v0.1.0` 릴리스 | 외부에서 실행 가능한 데모와 재현 가능한 릴리스가 공개된다. |

### Hardening: Day 9-14

| Day | 집중 영역 | 종료 조건 |
| ---: | --- | --- |
| 9 | 검색 오류 분석 및 튜닝 | 실패 질문을 유형별로 분류하고 Hybrid/Reranker 설정을 재평가한다. |
| 10 | PDF·OCR·표 edge case | 대표 실패 문서를 regression fixture로 추가하고 파싱 오류를 수정한다. |
| 11 | 인용 및 답변 보류 강화 | 잘못된 페이지 인용과 근거 없는 답변에 대한 회귀 테스트가 통과한다. |
| 12 | Agent·MCP 안정화 | 불필요한 Tool Call, 무한 재검색, timeout, 도구 실패 경로를 검증한다. |
| 13 | 성능·배포·문서 검수 | p95 latency, 오류 처리, Docker 재현성, 설치 문서를 검증한다. |
| 14 | 최종 버퍼 및 릴리스 승인 | 전체 평가와 데모 시나리오를 다시 실행하고 최종 태그를 확정한다. |

### Sprint Rules

- Day 1 종료 후 핵심 기술 스택을 변경하지 않는다.
- Day 2 종료 후 파싱 데이터 계약을 변경하지 않는다.
- Day 4 종료 후 신규 핵심 기능을 추가하지 않는다.
- Day 8에 기능 완성본을 배포한다.
- Day 9-14에는 실패 사례, 평가 점수, 안정성 개선만 수행한다.
- 모든 Day는 동작하는 커밋과 테스트 결과로 종료한다.

## 5. Initial GitHub Issues

- [ ] `docs/chore: define requirements, schemas and project foundation`
- [ ] `feat: build page-aware PDF, OCR and table ingestion pipeline`
- [ ] `feat: implement dense, BM25 and hybrid retrieval`
- [ ] `feat: add reranking, grounded answers and multi-document analysis`
- [ ] `feat: expose retrieval, document and citation MCP servers`
- [ ] `feat: orchestrate agentic retrieval with LangGraph`
- [ ] `eval: automate retrieval, citation and agent evaluation`
- [ ] `release: build UI, deploy demo and publish v0.1.0`

## 6. Issue Dependency

```text
Issue 1
  → Issue 2
  → Issue 3
  → Issue 4
  → Issue 5
  → Issue 6
  → Issue 7
  → Issue 8
```

각 Issue는 하루 안에 종료 가능한 Vertical Slice로 구성한다. Issue 8 이후 Day 9-14의 개선 사항은 평가 결과에서 발견된 실패 유형별 bug 또는 hardening Issue로 추가한다.
