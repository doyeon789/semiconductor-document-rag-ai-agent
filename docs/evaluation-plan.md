# Evaluation Plan

## 1. 목표

검색, 답변, 인용, 답변 보류, Agent 행동을 분리해서 측정한다. 최종 점수 하나로 문제를 숨기지 않고 어느 단계가 실패했는지 진단할 수 있어야 한다.

## 2. 평가 원칙

- 구현 전에 최소 평가 데이터셋을 만든다.
- 동일 데이터셋으로 baseline과 개선안을 비교한다.
- 모델, prompt, 검색 설정, index version, Git SHA를 기록한다.
- LLM judge만 사용하지 않고 정답 페이지·규칙 기반 지표를 함께 사용한다.
- 평균 점수뿐 아니라 질문 유형·문서 유형·언어별 결과를 공개한다.
- 평가 질문과 개발 prompt가 서로 오염되지 않도록 분리한다.

## 3. Dataset 구성

### 3.1 초기 규모

| Split | 문서 | 질문 | 용도 |
| --- | ---: | ---: | --- |
| development | 5~10 | 40~60 | 빠른 튜닝과 오류 분석 |
| validation | 5~10 | 40~60 | 설정 선택 |
| holdout | 별도 문서 포함 | 30 이상 | 최종 포트폴리오 결과 |

### 3.2 질문 유형 비율

| 유형 | 목표 비율 |
| --- | ---: |
| 단일 문서 fact lookup | 20% |
| procedure/troubleshooting | 15% |
| 다중 문서 비교 | 20% |
| 표 기반 질문 | 15% |
| 약어·한영 용어 질문 | 10% |
| 수치·장비 코드 exact 질문 | 10% |
| 답변 불가능 질문 | 10% |

한국어, 영어, 한영 혼합 질문을 모두 포함한다.

## 4. Dataset Schema

```json
{
  "question_id": "q-001",
  "question": "Vacuum Interlock의 원인과 조치 절차는?",
  "language": "ko",
  "intent": "procedure",
  "audience": "engineer",
  "document_ids": ["doc-1"],
  "answerable": true,
  "gold_pages": [42, 43],
  "gold_chunks": [],
  "reference_answer": "...",
  "required_facts": [
    "chamber pressure 확인",
    "vacuum valve 상태 확인"
  ],
  "forbidden_claims": [],
  "notes": "page 42 contains cause, page 43 contains procedure"
}
```

표 질문은 `gold_table_id`, 필요한 row/column 값을 추가한다. 다중 문서 비교는 문서별 `gold_pages`와 `required_facts`를 분리한다.

## 5. Retrieval Evaluation

### 5.1 Metrics

| Metric | 의미 |
| --- | --- |
| Recall@K | 정답 페이지/Chunk 중 Top-K에 포함된 비율 |
| Page Hit@K | 정답 페이지 하나 이상이 Top-K에 존재하는 질문 비율 |
| Precision@K | Top-K 결과 중 정답 비율 |
| MRR | 첫 정답의 역순위 평균 |
| nDCG@K | 다중 관련도와 순서를 고려한 점수 |
| Table Hit@K | 정답 표가 Top-K에 존재하는 비율 |

Chunk 정답이 없는 초기 데이터에서는 page-level 지표를 우선 사용한다.

### 5.2 비교 Configuration

```text
R1 Dense
R2 BM25
R3 Dense + BM25 + RRF
R4 R3 + Domain Expansion
R5 R4 + Cross-Encoder Reranking
```

각 run에서 latency, index size, query 비용도 기록한다.

### 5.3 초기 목표

| Metric | MVP Gate | Target |
| --- | ---: | ---: |
| Page Hit@5 | ≥ 0.80 | ≥ 0.90 |
| Recall@5 | ≥ 0.75 | ≥ 0.85 |
| MRR | ≥ 0.60 | ≥ 0.75 |
| Table Hit@5 | ≥ 0.70 | ≥ 0.85 |

초기 목표는 데이터셋 구축 후 난이도와 annotation 품질을 검토해 ADR 또는 평가 기록으로 조정한다.

## 6. Answer Evaluation

| Metric | 방법 |
| --- | --- |
| Required Fact Coverage | required facts 중 답변에 포함된 비율 |
| Faithfulness | Claim이 인용 Evidence로 지지되는 비율 |
| Answer Relevancy | 질문에 직접 답한 정도 |
| Contradiction Rate | Evidence와 충돌하는 Claim 비율 |
| Numeric Accuracy | 수치와 단위가 원문과 일치하는 비율 |
| Comparison Completeness | 비교 대상·항목별 근거가 모두 있는 비율 |

평가는 규칙 기반 extractor, 사람이 작성한 reference, 제한된 LLM judge를 조합한다. LLM judge prompt와 모델 version을 고정한다.

## 7. Citation Evaluation

### 7.1 Metrics

```text
Citation Precision = supported citations / all citations
Citation Coverage = claims with valid citation / citation-required claims
Page Match Accuracy = citations pointing to gold page / evaluated citations
Quote Match Rate = quote found on cited page / all quotes
```

### 7.2 초기 목표

| Metric | MVP Gate | Target |
| --- | ---: | ---: |
| Citation Precision | ≥ 0.90 | ≥ 0.97 |
| Citation Coverage | ≥ 0.90 | ≥ 0.95 |
| Page Match Accuracy | ≥ 0.90 | ≥ 0.97 |
| Quote Match Rate | ≥ 0.95 | ≥ 0.99 |

페이지 번호 오류는 답변 문체 오류보다 높은 우선순위로 수정한다.

## 8. Abstention Evaluation

답변 가능/불가능 질문을 함께 평가한다.

| Metric | 의미 |
| --- | --- |
| Abstention Precision | 보류한 질문 중 실제 답변 불가능 비율 |
| Abstention Recall | 답변 불가능 질문 중 보류한 비율 |
| Unsafe Answer Rate | 답변 불가능 질문에 근거 없는 답변을 한 비율 |
| False Abstention Rate | 답변 가능한 질문을 불필요하게 보류한 비율 |

초기 gate:

- Abstention Precision ≥ 0.80
- Abstention Recall ≥ 0.85
- Unsafe Answer Rate ≤ 0.05

## 9. Agent Evaluation

### 9.1 Metrics

- Intent Classification Accuracy
- Tool Selection Accuracy
- Retrieval Retry Success Rate
- Average Tool Calls
- Unnecessary Tool Call Rate
- Termination Accuracy
- Max-step Violation Count
- Tool Error Recovery Rate

### 9.2 Trajectory Cases

| Case | 기대 경로 |
| --- | --- |
| 충분한 단일 검색 | classify → retrieve → gather → generate → validate |
| 검색어 재작성 필요 | classify → retrieve → rewrite → retrieve → generate |
| 표 검색 | classify → search_table → get_table → generate |
| 근거 없음 | retrieve → rewrite → retrieve → abstain |
| MCP 오류 | tool error → retry/fallback → answer 또는 abstain |
| Citation 오류 | generate → validate → repair → validate |

## 10. Performance & Cost

| Metric | 목표 |
| --- | --- |
| Search p95 warm latency | ≤ 2초 |
| Answer p95 latency | ≤ 15초 |
| Agent timeout | ≤ 45초 |
| 평균 retrieval attempts | ≤ 1.5 |
| 평균 tool calls | 질문 유형별 baseline 대비 관리 |
| LLM token/cost | run별 기록, 예산 초과 시 실패 |

## 11. 실행 절차

```text
1. dataset schema 검증
2. 문서/index version 고정
3. configuration snapshot 저장
4. retrieval suite 실행
5. answer/citation suite 실행
6. abstention suite 실행
7. agent trajectory suite 실행
8. aggregate + slice metrics 생성
9. 실패 사례 artifact 저장
10. 이전 baseline과 diff 생성
```

## 12. Report Structure

```text
reports/{evaluation_run_id}/
├── manifest.json
├── aggregate_metrics.json
├── slice_metrics.json
├── retrieval_results.jsonl
├── retrieval_failures.jsonl
├── answer_results.jsonl
├── agent_trajectories.jsonl
├── retrieval_error_analysis.md
├── failures.md
└── summary.md
```

`manifest.json` 필수 필드:

```json
{
  "git_sha": "...",
  "dataset_version": "eval-v1",
  "parser_version": "...",
  "chunker_version": "...",
  "embedding_version": "...",
  "reranker_version": "...",
  "llm_model": "...",
  "prompt_version": "...",
  "configuration": {}
}
```

## 13. 자동 평가 실행

Day 7 전체 평가는 다음 한 명령으로 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py
```

기본 입력은 `data/evaluation/rag_cases.json`의 14개 케이스와 로컬 PDF v1.3이다. 실행 결과는 Git에서 제외되는 `output/evaluation/{run_id}/`에 저장되며 기존 report artifact 외에 개인정보를 담지 않는 `events.jsonl`도 생성한다.

2026-08-13 기준 실행 `20260813T084208Z-df07180`의 주요 결과는 다음과 같다.

| 항목 | 결과 |
| --- | ---: |
| Rerank Page Hit@5 | 1.000 |
| Rerank Recall@5 | 0.917 |
| Rerank MRR | 0.819 |
| Citation Precision | 1.000 |
| Page Match Accuracy | 0.417 |
| Abstention Recall | 0.500 |
| Unsafe Answer Rate | 0.500 |
| Trajectory Accuracy | 0.929 |

검색 재순위화는 retrieval gate를 통과했지만, 정답 페이지 외의 근거를 답변에 포함하는 문제와 답변 불가 질문에 답한 문제가 확인되어 전체 MVP Gate는 실패했다. 이 결과는 Day 9 retrieval error analysis와 Day 11 citation·abstention hardening의 기준값으로 사용한다.

Day 9에는 검색 결과, Citation 페이지와 검색 모드별 순위를 결합해 `missed`, `low_rank`, `wrong_page`, `rerank_regression`을 자동 분류하도록 했다. Evidence 선택을 질문 개념 기준으로 개선한 로컬 검증에서 Required Fact Coverage `0.917`, Page Match Accuracy `0.597`, Case Pass Rate `0.357`을 기록했다. Retrieval 지표는 기준값을 유지했으며, 답변 불가능 질문에 대한 보류 개선은 Day 11에서 다룬다.

Day 11에는 Evidence Pack에 검색 방식을 보존하고 현재 Reranker의 관련도 점수 `-1.0`을 근거 충분성 기준으로 적용했다. Native RAG와 Agentic RAG 모두 약한 최종 근거를 답변 대신 보류한다. 개발 평가에서 Abstention Recall `1.000`, Unsafe Answer Rate `0.000`, Trajectory Accuracy `1.000`을 기록했고 답변 가능한 질문의 False Abstention은 발생하지 않았다. 별도 holdout이 아직 없으므로 threshold의 최종 확정은 Day 14 평가에서 수행한다.

## 14. Release Gate

`v0.1.0` 릴리스 전 다음 조건을 모두 만족한다.

- Retrieval MVP gate 통과
- Citation MVP gate 통과
- Unsafe Answer Rate 5% 이하
- 필수 trajectory case 통과
- 평가 run 재실행 가능
- 이전 baseline 대비 주요 지표 회귀 없음
- 알려진 실패와 제외 범위를 README 또는 release note에 공개

## 15. 관련 문서

- [Requirements](./requirements.md)
- [Retrieval Design](./retrieval-design.md)
- [Testing Strategy](./testing-strategy.md)

