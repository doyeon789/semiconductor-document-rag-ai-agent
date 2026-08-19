# ADR-0002: Local Hybrid Retrieval

- Status: Accepted
- Date: 2026-08-07
- Updated: 2026-08-19

## Context

AI 보안 문서에는 의미가 비슷한 설명과 함께 `AI RMF`, `LLM01`, 기관 고유 용어처럼 exact match가 중요한 표현이 섞여 있습니다. Dense만 사용하면 식별자를 놓칠 수 있고 BM25만 사용하면 한국어·영어의 의미적 연결이 약합니다.

초기 설계는 Qdrant와 OpenSearch를 제안했지만, 현재 6개 문서 규모에서 두 서버를 운영하는 비용은 검색 품질에 직접 기여하지 않습니다.

## Decision

- BM25와 Dense index를 Python 프로세스 메모리에 만듭니다.
- Dense embedding은 FastEmbed의 다국어 로컬 모델을 사용합니다.
- 두 순위를 Reciprocal Rank Fusion으로 결합합니다.
- Hybrid 상위 후보에 다국어 Cross-Encoder Reranker를 적용합니다.
- 모든 모드를 같은 Chunk와 평가셋에서 비교합니다.
- 외부 vector/keyword 검색 서버는 현재 사용하지 않습니다.

## Consequences

### Positive

- 별도 서비스 없이 Windows 로컬과 CI에서 재현할 수 있습니다.
- BM25·Dense·Hybrid·Rerank 효과를 독립적으로 비교할 수 있습니다.
- 현재 코퍼스 규모에서 운영 복잡도보다 검색 실험에 집중할 수 있습니다.

### Negative

- 프로세스를 재시작하면 index를 다시 만듭니다.
- 코퍼스가 커지면 메모리와 시작 시간이 늘어납니다.
- 분산 검색과 증분 색인을 지원하지 않습니다.

## Alternatives

- Qdrant + OpenSearch: 현재 규모에는 과도해 보류했습니다.
- Dense only: exact term 검색 약화 때문에 제외했습니다.
- BM25 only: 한영 의미 검색 한계 때문에 baseline으로만 유지합니다.

## Revisit Conditions

- 로컬 index가 메모리나 시작 시간 목표를 넘는 경우
- 문서 업로드·증분 색인·다중 프로세스 공유가 필요한 경우
- 외부 엔진이 holdout 검색 품질이나 latency를 유의미하게 개선하는 경우

## Validation

- 네 검색 모드의 동일 평가셋 비교
- exact term, 한영 교차, 기관 간 비교 slice
- Page Hit@5, MRR, Page Match Accuracy와 warm latency
