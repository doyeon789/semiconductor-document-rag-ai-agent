# Evaluation Plan

## 1. 목표

검색, Evidence 선택, Citation, 답변 보류와 Agent 경로를 분리해 측정합니다. 평균 점수 하나로 실패 원인을 숨기지 않고 문서·언어·질문 유형별로 분석합니다.

## 2. 기준값의 구분

기존 자동 평가는 단일 로컬 PDF와 그 질문셋을 사용했습니다.

| 지표 | 기존 기준값 |
| --- | ---: |
| Rerank Page Hit@5 | 1.000 |
| Recall@5 | 0.917 |
| MRR | 0.819 |
| Required Fact Coverage | 0.917 |
| Page Match Accuracy | 0.597 |
| Abstention Recall | 1.000 |
| Unsafe Answer Rate | 0.000 |
| Trajectory Accuracy | 1.000 |

이 값은 코드 회귀를 확인하는 참고값이며 새 AI 보안 코퍼스의 성능이 아닙니다. 새 코퍼스 기준선은 아래의 schema v2 평가셋과 `document_id + page_number` 판정을 사용합니다.

## 3. AI 보안 평가셋

### Split

| Split | 최소 질문 | 용도 |
| --- | ---: | --- |
| development | 30 | Chunk·검색·threshold 튜닝 |
| holdout | 15 | 선택한 설정의 최종 검증 |

같은 질문의 표현만 바꾼 항목을 서로 다른 split에 넣지 않습니다. 현재 split은 질문 ID·문장뿐 아니라 `document_id + gold page`도 서로 겹치지 않게 고정했습니다.

현재 파일:

- `data/evaluation/ai_security_retrieval_dev.json`: development 30문항
- `data/evaluation/ai_security_retrieval_holdout.json`: holdout 15문항

두 split 모두 한국어·영어·한영 혼합, 단일 문서와 기관 간 비교 질문을 포함합니다. 검색 순위 지표는 정답 페이지가 있는 질문만 계산합니다. 답변 불가능·프롬프트 인젝션 질문은 검색 지표의 분모를 왜곡하지 않도록 기존 RAG 품질 평가에서 별도로 유지하며, 다중 문서 답변·Citation 전환 때 확장합니다.

### 질문 유형

| 유형 | 예시 |
| --- | --- |
| 단일 문서 fact | 특정 위험이나 통제의 정의 |
| 절차·목록 | 레드티밍 또는 위험관리 단계 |
| 기관 간 비교 | KISA·NIST·OWASP 권고의 공통점과 차이 |
| exact term | `LLM01`, `GOVERN`, `MEASURE` 등 정확한 식별자 |
| 한영 교차 | 한국어 질문→영어 문서, 영어 질문→한국어 문서 |
| 다중 페이지 | 원인과 대응이 다른 페이지에 있는 질문 |
| 답변 불가능 | 여섯 문서에 근거가 없는 최신 사실·제품 질문 |

### Case schema

```json
{
  "id": "AISEC-DEV-026",
  "query": "KISA와 OWASP 2026은 프롬프트 인젝션을 어떻게 설명하며 어떤 입력 표면을 위험으로 보는가?",
  "language": "ko",
  "intent": "cross_document",
  "gold": [
    {
      "document_id": "kisa-ai-security-guide-corrected-2026",
      "pages": [52]
    },
    {
      "document_id": "owasp-genai-llm-top-10-2026",
      "pages": [10]
    }
  ]
}
```

정답 페이지는 PDF를 직접 확인해 기록하고, 근거가 여러 기관에 걸치면 문서별로 분리합니다.

## 4. 검색 지표

| 지표 | 의미 | 초기 Gate |
| --- | --- | ---: |
| Page Hit@5 | 정답 문서·페이지 하나 이상이 Top-5에 포함된 질문 비율 | ≥ 0.85 |
| Recall@5 | 필요한 정답 페이지 중 Top-5에 포함된 비율 | ≥ 0.75 |
| MRR | 첫 정답 문서·페이지의 역순위 평균 | ≥ 0.65 |
| Cross-language Page Hit@5 | `cross_language` 질문의 Page Hit@5 | ≥ 0.75 |
| Document Coverage@5 | 질문별 정답 문서 회수 비율의 평균 | ≥ 0.80 |
| Cross-document Full Coverage@5 | 비교 질문에서 필요한 문서를 모두 검색한 비율 | ≥ 0.80 |

`document_id + page_number`를 정답 단위로 사용합니다. 페이지 번호만 같고 문서가 다른 결과는 정답이 아닙니다.

### 2026-08-24 baseline

development는 commit `5c49c76`, dev와 정답 페이지를 완전히 분리해 다시 검증한 holdout은 commit `fe97086`에서 측정했습니다. 조건은 Top-5, 6개 문서 757개 검색 가능 페이지, 1,282개 Chunk, Windows CPU 환경입니다. 임베딩은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, Reranker는 `jinaai/jina-reranker-v2-base-multilingual`입니다. development 정확도는 반복 실행에서 동일했고 latency만 시스템 부하에 따라 달라졌으므로, 아래 latency는 모델과 인덱스 준비를 제외한 현재 개발 환경의 모드 간 비교값으로 해석합니다.

| Split·모드 | Page Hit@5 | Document Coverage@5 | Recall@5 | MRR | NDCG@5 | prepared p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| development · BM25 | 0.700 | 0.733 | 0.683 | 0.575 | 0.597 | 41.94 ms |
| development · Dense | **0.767** | **0.833** | **0.700** | 0.552 | 0.566 | 337.40 ms |
| development · Hybrid | 0.733 | 0.733 | 0.683 | **0.631** | **0.624** | 463.27 ms |
| development · Rerank | 0.733 | 0.750 | **0.700** | 0.598 | 0.619 | 23,878.46 ms |
| holdout · Dense | 0.467 | 0.867 | 0.433 | 0.283 | 0.314 | 394.16 ms |

development의 1차 선택 기준은 Page Hit@5와 Document Coverage이므로 Dense를 선택했고 holdout에는 Dense만 적용했습니다. Aggregate만으로 실패 원인을 숨기지 않기 위해 case-level 결과를 질문셋의 `intent`와 결합해 다음 slice도 확인했습니다.

| Dense slice | Development | Holdout |
| --- | ---: | ---: |
| Cross-document 평균 문서 커버리지 | 0.500 (4문항) | 0.667 (3문항) |
| Cross-document 전체 문서 회수 | 0/4 | 1/3 |
| Cross-document Page Hit@5 | 0.750 | 0.333 |
| Cross-language Page Hit@5 | 0.286 (7문항) | 0.250 (4문항) |

따라서 전체 holdout Document Coverage@5 0.867만으로 문서 선택이 해결됐다고 볼 수 없습니다. 정확한 절·페이지 순위와 기관 간 비교의 문서 균형, 한영 교차 검색이 모두 현재 병목입니다. Rerank는 정확도를 개선하지 못하면서 평균 20초 이상이므로 현재 설정을 기본값으로 채택하지 않습니다. 현재 CLI는 aggregate와 case-level 결과를 저장하며 slice 자동 집계는 다음 평가 도구 개선 항목으로 남깁니다.

### 2026-08-25 보수적 절 문맥 실험

Commit `eed40db`에서 Chunk 경계와 원문은 유지하고, 짧은 ASCII 2단계 절 제목과 NIST function 표 제목을 같은 페이지의 후속 Chunk에만 검색 문맥으로 추가했습니다. 실제로 `retrieval_text`가 달라진 Chunk는 42/1,282개이며 Evidence·Citation·API는 계속 원문 `text`를 사용합니다.

| Split | Page Hit@5 | Document Coverage@5 | Recall@5 | MRR | NDCG@5 | prepared p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| development · baseline | 0.767 | 0.833 | 0.700 | 0.552 | 0.566 | 337.40 ms |
| development · section context | 0.767 | 0.833 | 0.700 | **0.559** | **0.572** | 326.66 ms |
| holdout · baseline | 0.467 | 0.867 | 0.433 | 0.283 | **0.314** | 394.16 ms |
| holdout · section context | 0.467 | 0.867 | 0.433 | 0.283 | 0.309 | 337.90 ms |

Development에서는 `AISEC-DEV-019`가 3위에서 2위, `AISEC-DEV-022`가 5위에서 4위로 올랐고 정답 순위 하락은 없었습니다. 설정 선택 뒤 한 번 실행한 holdout에서는 주요 지표와 첫 정답 1위가 같았지만, 정답이 21·22쪽인 `AISEC-HOLD-012`에서 두 번째 정답 21쪽이 2위에서 3위로 내려가 NDCG@5가 0.005 낮아졌습니다. 이 변경은 primary metric 회귀가 없는 작은 순위 개선으로 유지하되, Chunk 구조 단계의 Page Hit 개선 Gate를 통과한 것으로 판정하지 않습니다.

## 5. 답변과 Citation 지표

| 지표 | 초기 Gate |
| --- | ---: |
| Required Fact Coverage | ≥ 0.80 |
| Citation Precision | ≥ 0.95 |
| Citation Coverage | ≥ 0.95 |
| Page Match Accuracy | ≥ 0.90 |
| Quote Match Rate | 1.00 |
| Comparison Document Coverage | ≥ 0.85 |

추출형 답변에서 `Quote Match Rate`는 반드시 1.00이어야 합니다. 잘못된 페이지 Citation은 문체 문제보다 높은 우선순위로 수정합니다.

## 6. 답변 보류와 Agent 지표

- Abstention Precision
- Abstention Recall
- Unsafe Answer Rate
- False Abstention Rate
- Trajectory Accuracy
- 평균 retrieval attempts와 step 수
- Tool timeout·error 종료 정확성

초기 Gate:

- Abstention Recall ≥ 0.90
- Unsafe Answer Rate = 0.00
- 최대 step 위반 = 0

## 7. 실험 규칙

1. 코퍼스 해시와 평가셋 버전을 고정합니다.
2. BM25, Dense, Hybrid, Rerank baseline을 모두 실행합니다.
3. 한 실험에서는 Chunk, 모델, 후보 수, threshold 중 하나만 바꿉니다.
4. development 결과로 설정을 선택합니다.
5. holdout은 최종 선택 때만 실행합니다.
6. JSON에는 점수, prepared latency, 모델명과 설정을 저장하고 Git SHA·실행 환경은 결과 파일명과 실험 기록에 함께 남깁니다.

## 8. 실행

AI 보안 development 평가:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
```

동결된 holdout은 development에서 설정을 선택한 뒤에만 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py `
  --dataset data\evaluation\ai_security_retrieval_holdout.json `
  --modes dense
```

기존 단일 문서 RAG 회귀 평가는 별도로 유지합니다.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py
```

평가 산출물은 Git에서 제외된 `output/evaluation/`에 저장합니다.

## 9. 실패 분석 순서

1. `missed`, `low_rank`, `wrong_page`, `rerank_regression` 분류
2. `cross_language`, `document_imbalance` 추가 분류
3. 정답 페이지 text 추출 상태 확인
4. Chunk 경계와 반복 header/footer 확인
5. BM25·Dense 개별 순위 비교
6. Reranker 전후 순위 비교
7. Evidence 선택과 Citation 포함 이유 확인

인프라나 모델 교체보다 먼저 실패한 실제 페이지와 질문을 확인합니다.
