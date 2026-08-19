# Performance-First Roadmap

## 원칙

작업 순서는 날짜나 기능 수가 아니라 **현재 품질 병목을 얼마나 직접 줄이는지**로 결정합니다. MCP, 대규모 검색 인프라, 문서 업로드와 외부 LLM은 평가 결과 없이 먼저 추가하지 않습니다.

## 1. 다중 문서 코퍼스 연결

- `data/corpus/sources.yaml`의 6개 문서를 한 번에 로드합니다.
- 문서별 `source_id`, 제목, 기관, 언어, 버전과 제외 페이지를 Chunk에 연결합니다.
- 검색 결과와 Citation이 정확한 문서와 PDF를 가리키게 합니다.
- 같은 페이지 번호를 가진 서로 다른 문서가 섞이지 않는 테스트를 추가합니다.

완료 기준: 6개 PDF 773쪽에서 제외 페이지를 빼고 인덱스를 만들며 모든 검색 결과가 원본 문서와 페이지로 역추적됩니다.

## 2. AI 보안 평가셋 구축

- KISA·NIST·OWASP 문서별 정답 페이지를 직접 확인합니다.
- 한국어, 영어, 한영 혼합 질문을 포함합니다.
- 단일 문서, 기관 간 비교, exact term, 답변 불가능 질문을 분리합니다.
- 기존 단일 문서 평가 결과는 회귀 참고값으로만 남깁니다.

완료 기준: 최소 30개 개발 질문과 별도 holdout 질문이 있고, 질문마다 `document_id`와 `gold_pages`가 있습니다.

## 3. Chunk와 문서 구조 개선

- 반복 머리말·꼬리말과 목차 노이즈를 제거합니다.
- 제목과 절 경계를 Chunk metadata에 보존합니다.
- 긴 페이지의 고정 페이지 Chunk와 절 기반 Chunk를 비교합니다.
- 인접 페이지 문맥 확장은 평가에서 필요한 경우에만 적용합니다.

완료 기준: 같은 검색 모델에서 Page Hit@5와 MRR이 baseline보다 개선되고 Citation 오염이 늘지 않습니다.

## 4. 검색·Reranking 튜닝

- BM25, Dense, Hybrid, Rerank를 새 평가셋에서 다시 비교합니다.
- 한국어↔영어 기관 용어와 AI 보안 약어의 검색 실패를 분석합니다.
- 후보 수, RRF 상수, Reranker 모델과 threshold를 한 번에 하나씩 변경합니다.
- 점수 향상이 없는 복잡도는 제거합니다.

완료 기준: holdout Page Hit@5와 MRR 목표를 만족하고 warm latency 회귀가 허용 범위 안입니다.

## 5. Evidence와 Citation 정밀화

- 질문 개념을 직접 지지하는 Evidence만 답변에 포함합니다.
- 기관 간 비교 질문에서 각 주장에 서로 다른 문서 Citation을 강제합니다.
- 정답 외 페이지가 Citation에 포함되는 원인을 자동 분류합니다.
- 답변 보류 threshold를 새 데이터셋으로 다시 보정합니다.

완료 기준: Citation Precision과 Page Match Accuracy가 모두 기준을 통과하며 Unsafe Answer Rate가 0에 가깝게 유지됩니다.

## 6. 데모 전환과 정리

- API와 Streamlit의 단일 문서 상수를 다중 문서 metadata로 교체합니다.
- AI 보안 예시 질문과 문서 필터를 제공합니다.
- 새 코퍼스 평가 결과만 README에 게시합니다.
- 필요성이 없는 옛 단일 문서 fixture와 이름을 제거합니다.

## 보류하는 항목

- MCP 서버
- Qdrant·OpenSearch·PostgreSQL·MinIO 운영
- 문서 업로드·사용자 권한 관리
- OCR과 복잡한 표 파싱
- 외부 LLM 기반 생성 답변

이 항목들은 현재 평가에서 명확한 문제를 해결하거나 실제 배포 요구가 생길 때 별도 ADR과 함께 검토합니다.
