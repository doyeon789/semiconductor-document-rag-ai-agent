# Development Plan

## 1. 목표

반도체 PDF, 공정 문서, 장비 매뉴얼, 논문을 대상으로 다음 흐름을 단계적으로 구현한다.

```text
문서 처리
  → 페이지 기반 검색
  → Hybrid Search 및 Reranking
  → 근거 기반 답변과 인용 검증
  → LangGraph Agent와 typed in-process tool 연동
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

### Phase 5. LangGraph Agent 및 Typed Tools

MVP에서는 [ADR-0006](./adr/0006-in-process-agent-tools.md)에 따라 내부 typed tool을 사용한다. 아래 MCP 서버 설계는 외부 프로세스나 다중 클라이언트가 필요해질 때의 후속 확장 범위다.

#### 후속 MCP 서버 확장안

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

- 각 typed tool을 Agent 없이 독립적으로 테스트할 수 있다.
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

## 4. Quality & Performance Milestones

달력 일정 대신 평가 결과에서 가장 큰 병목을 먼저 처리한다. 기능 범위는 고정하고 Page Match, 사실 커버리지, 안전성, 지연 시간을 순서대로 개선한다.

### Capability Foundation

| 영역 | 상태 | 종료 조건 |
| --- | --- | --- |
| 프로젝트 기반 | 완료 | FastAPI health check, CI, 데이터 계약과 샘플 문서가 준비된다. |
| PDF 처리 | 완료 | 모든 Chunk와 Citation을 원문 PDF 페이지로 역추적한다. |
| 검색 | 완료 | Dense, BM25, Hybrid, Rerank를 동일 평가셋으로 비교한다. |
| 근거 답변 | 완료 | 답변·보류·페이지 Citation과 quote 검증이 동작한다. |
| Agent | 완료 | LangGraph가 검색, 재검색, 답변 또는 보류 경로를 유한하게 실행한다. |
| 자동 평가 | 완료 | 검색·답변·인용·Agent 리포트와 재현 가능한 trace가 생성된다. |
| 로컬 Demo | 완료 | FastAPI와 Streamlit에서 질문부터 PDF 페이지 확인까지 실행된다. |

### Performance Backlog

| 우선순위 | 집중 영역 | 현재 값·문제 | 종료 조건 |
| ---: | --- | --- | --- |
| P0 | 다중 단계 근거 복원 | Q12가 두 페이지의 인과 사실 중 하나만 답변 | Required Fact Coverage `1.000`과 Page Match `1.000` 동시 유지 |
| P1 | Rerank 지연 | p95 약 `6.1초` | 동일 Retrieval 지표에서 p95 `2초` 이하 |
| P2 | Holdout 검증 | 개발 평가 14건만 존재 | 별도 holdout에서 threshold 과적합 여부 확인 |
| P3 | PDF·OCR·표 edge case | 현재 PDF 중심 fixture | 대표 실패 문서를 regression fixture로 추가 |
| P4 | Release 승인 | 로컬 Demo와 개발 평가 통과 | clean clone 재현, 전체 평가, 릴리스 문서 확정 |

### Execution Rules

- 성능 변경 전 실패 evaluation case 또는 회귀 테스트를 먼저 고정한다.
- 한 번에 하나의 품질 지표 또는 병목만 개선한다.
- Page Match, Citation Precision, Unsafe Answer Rate의 회귀를 허용하지 않는다.
- 모든 작업은 동작하는 커밋과 테스트·평가 결과로 종료한다.

## 5. Outcome-based GitHub Issues

- [x] `docs/chore: define requirements, schemas and project foundation`
- [x] `feat: build page-aware PDF ingestion pipeline`
- [x] `feat: implement local BM25, Dense, Hybrid and Rerank retrieval`
- [x] `feat: add grounded answers and page Citation`
- [x] `feat: orchestrate agentic retrieval with LangGraph`
- [x] `eval: automate retrieval, citation and agent evaluation`
- [x] `feat: connect the local Streamlit demo`
- [ ] `perf: recover multi-page causal evidence without citation regression`
- [ ] `perf: reduce reranker p95 latency`
- [ ] `release: verify clean setup and publish v0.1.0`

## 6. Issue Dependency

```text
다중 단계 근거 복원
  → Rerank 지연 개선
  → Holdout 전체 평가
  → clean setup 검증
  → v0.1.0 승인
```

각 Issue는 하나의 평가 병목을 해결하는 Vertical Slice로 구성한다. 새로운 작업은 평가 결과에서 발견된 실패 유형별 bug, performance 또는 hardening Issue로 추가한다.
