# Evaluation Plan

## 1. 목표

검색, Evidence 선택, Citation, 답변 보류와 Agent 경로를 분리해 측정합니다. 평균 점수 하나로 실패 원인을 숨기지 않고 문서·언어·질문 유형별로 분석합니다.

## 2. 현재 기준값의 의미

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

이 값은 코드 회귀를 확인하는 참고값이며 새 AI 보안 코퍼스의 성능이 아닙니다. 코퍼스·질문 분포·문서 수가 달라지므로 새 평가셋에서 baseline을 다시 만듭니다.

## 3. AI 보안 평가셋

### Split

| Split | 최소 질문 | 용도 |
| --- | ---: | --- |
| development | 30 | Chunk·검색·threshold 튜닝 |
| holdout | 15 | 선택한 설정의 최종 검증 |

같은 질문의 표현만 바꾼 항목을 서로 다른 split에 넣지 않습니다. 가능하면 holdout은 튜닝에서 덜 사용한 문서·절을 포함합니다.

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
  "question_id": "ai-sec-001",
  "question": "생성형 AI의 프롬프트 인젝션 위험과 완화책은?",
  "language": "ko",
  "intent": "cross_document",
  "answerable": true,
  "gold": [
    {
      "document_id": "owasp-genai-llm-top-10-2026",
      "pages": [20, 21]
    }
  ],
  "required_facts": ["위험 설명", "권고 통제"],
  "forbidden_claims": []
}
```

정답 페이지는 PDF를 직접 확인해 기록하고, 근거가 여러 기관에 걸치면 문서별로 분리합니다.

## 4. 검색 지표

| 지표 | 의미 | 초기 Gate |
| --- | --- | ---: |
| Page Hit@5 | 정답 문서·페이지 하나 이상이 Top-5에 포함된 질문 비율 | ≥ 0.85 |
| Recall@5 | 필요한 정답 페이지 중 Top-5에 포함된 비율 | ≥ 0.75 |
| MRR | 첫 정답 문서·페이지의 역순위 평균 | ≥ 0.65 |
| Cross-language Page Hit@5 | 한영 교차 질문의 Page Hit@5 | ≥ 0.75 |
| Document Coverage | 비교 질문에서 필요한 문서가 모두 검색된 비율 | ≥ 0.80 |

`document_id + page_number`를 정답 단위로 사용합니다. 페이지 번호만 같고 문서가 다른 결과는 정답이 아닙니다.

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
6. 점수, warm latency, 모델명, 설정과 Git SHA를 함께 저장합니다.

## 8. 실행

현재 회귀 평가:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
.\.venv\Scripts\python.exe scripts\evaluate_rag.py
```

현재 기본 입력은 기존 단일 문서 평가셋입니다. 다중 문서 loader는 연결됐지만 AI 보안 gold page 평가셋이 아직 없으므로 결과를 새 코퍼스 성능으로 게시하지 않습니다.

평가 산출물은 Git에서 제외된 `output/evaluation/{run_id}/`에 저장합니다.

## 9. 실패 분석 순서

1. `missed`, `low_rank`, `wrong_page`, `rerank_regression` 분류
2. `cross_language`, `document_imbalance` 추가 분류
3. 정답 페이지 text 추출 상태 확인
4. Chunk 경계와 반복 header/footer 확인
5. BM25·Dense 개별 순위 비교
6. Reranker 전후 순위 비교
7. Evidence 선택과 Citation 포함 이유 확인

인프라나 모델 교체보다 먼저 실패한 실제 페이지와 질문을 확인합니다.
