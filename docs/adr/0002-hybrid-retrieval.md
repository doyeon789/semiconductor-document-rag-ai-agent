# ADR-0002: Qdrant + OpenSearch Hybrid Retrieval

- Status: Accepted
- Date: 2026-08-07
- Decision owners: Project maintainer

## Context

반도체 문서는 의미가 비슷한 표현뿐 아니라 `EUV`, `RF-102`, recipe 이름, 압력·온도·선택비 같은 exact term이 중요하다. Dense Search만 사용하면 정확한 코드와 희귀 약어를 놓칠 수 있고, BM25만 사용하면 한영 표현과 의미적 유사성을 놓칠 수 있다.

## Decision

- Dense Vector Search는 Qdrant를 사용한다.
- Keyword/BM25 Search는 OpenSearch를 사용한다.
- 두 backend를 병렬 호출하고 Reciprocal Rank Fusion으로 결합한다.
- Fusion 상위 후보에 Cross-Encoder Reranker를 적용한다.
- PostgreSQL을 metadata source of truth로 사용하고 두 인덱스는 재생성 가능한 projection으로 취급한다.
- 하나의 검색 backend가 실패하면 나머지 결과로 degraded response를 제공한다.

## Consequences

### Positive

- 의미 검색과 exact term 검색을 독립적으로 튜닝할 수 있다.
- Dense, BM25, Hybrid 개선 효과를 명확히 비교할 수 있다.
- 검색 backend별 장애 격리가 가능하다.
- 포트폴리오에서 Hybrid Retrieval 설계와 평가를 구체적으로 보여줄 수 있다.

### Negative

- 로컬·배포 환경에서 운영할 서비스가 늘어난다.
- 두 인덱스의 version과 활성 문서를 동기화해야 한다.
- score scale이 달라 rank-based fusion이 필요하다.

## Alternatives Considered

### OpenSearch only

운영은 단순하지만 Dense와 BM25 실험 및 payload 모델이 한 컴포넌트에 결합된다.

### PostgreSQL + pgvector

MVP 인프라는 단순해지지만 한국어 BM25와 검색 분석기 실험 범위가 제한될 수 있다.

### Qdrant dense+sparse only

단일 vector engine으로 단순화할 수 있으나 OpenSearch의 exact field와 BM25 분석기 실험을 포기해야 한다.

## Validation

- Dense, BM25, Hybrid, Hybrid+Reranker 동일 평가셋 비교
- Qdrant/OpenSearch 개별 장애 fallback test
- index version mismatch test
- exact 장비 코드와 한영 동의어 slice 지표 비교

## Revisit Conditions

- 배포 환경 자원으로 두 엔진을 운영할 수 없는 경우
- 단일 엔진이 동일 평가 점수와 latency를 만족하는 경우
- 데이터 규모가 PostgreSQL 단일 구성으로 충분하다고 입증된 경우

## Related Documents

- [Retrieval Design](../retrieval-design.md)
- [Evaluation Plan](../evaluation-plan.md)

