# Performance-First Roadmap

## 원칙

작업 순서는 날짜나 기능 수가 아니라 **현재 품질 병목을 얼마나 직접 줄이는지**로 결정합니다. MCP, 대규모 검색 인프라, 문서 업로드와 외부 LLM은 평가 결과 없이 먼저 추가하지 않습니다.

## 1. 다중 문서 코퍼스 연결 — 완료

- `data/corpus/sources.yaml`의 6개 문서를 한 번에 로드합니다.
- 문서별 `source_id`, 제목, 기관, 언어, 버전과 제외 페이지를 Chunk에 연결합니다.
- 검색 결과와 Citation이 정확한 문서와 PDF를 가리키게 합니다.
- 같은 페이지 번호를 가진 서로 다른 문서가 섞이지 않는 테스트를 추가합니다.

완료 기준: 6개 PDF 773쪽에서 제외 페이지를 빼고 인덱스를 만들며 모든 검색 결과가 원본 문서와 페이지로 역추적됩니다.

## 2. AI 보안 평가셋 구축 — 완료

- KISA·NIST·OWASP 문서별 정답 페이지를 직접 확인합니다.
- 한국어, 영어, 한영 혼합 질문을 포함합니다.
- 단일 문서, 기관 간 비교, exact term, 한영 교차 질문을 분리합니다.
- 기존 단일 문서 평가 결과는 회귀 참고값으로만 남깁니다.

완료 기준: development 30문항과 별도 holdout 15문항이 있고, 질문마다 하나 이상의 `document_id + gold page`가 있습니다. 답변 불가능 질문은 양성 검색 지표와 섞지 않고 RAG 품질 평가에서 별도로 다룹니다.

## 3. Chunk와 문서 구조 개선 — 1차 실험 완료, Gate 미달

Dense 기준선은 development Page Hit@5 0.767, MRR 0.552이고 holdout Page Hit@5 0.467, MRR 0.283입니다. 정확한 절·페이지 순위가 낮고, 기관 간 비교 질문의 전체 문서 회수도 development 0/4, holdout 1/3에 그쳤습니다.

- [x] 원문과 검색 입력을 분리하고 같은 페이지의 보수적 NIST 절·표 문맥을 보존합니다.
- [x] Chunk 경계·ID·hash 불변과 Citation 원문 격리를 테스트합니다.
- [ ] 반복 머리말·꼬리말과 목차 노이즈 제거는 별도 단일 변수로 검증합니다.
- [ ] 글꼴 metadata가 필요할 때 한국어 제목과 체크리스트 행을 구분합니다.
- [ ] 긴 페이지의 고정 페이지 Chunk와 절 기반 Chunk를 비교합니다.

2026-08-25 commit `eed40db`의 1차 실험은 development Page Hit@5를 0.767로 유지하고 MRR을 0.552에서 0.559로 높였습니다. Holdout Page Hit@5와 MRR은 각각 0.467, 0.283으로 같았고 NDCG@5는 0.314에서 0.309로 소폭 낮아졌습니다. 원문 오염은 없지만 Page Hit 개선 기준에는 아직 도달하지 못했습니다.

완료 기준: 같은 검색 모델에서 Page Hit@5와 MRR이 baseline보다 개선되고 Citation 오염이 늘지 않습니다. 다음 구조 실험은 실제 실패 질문이 글꼴 기반 제목이나 표 구조의 필요성을 보여줄 때 재개합니다.

## 4. 검색·Reranking 튜닝 — 다음 우선순위

- BM25, Dense, Hybrid, Rerank를 새 평가셋에서 다시 비교합니다.
- 한국어↔영어 기관 용어와 AI 보안 약어를 이용한 질의 확장을 먼저 비교합니다.
- 후보 수, RRF 상수, Reranker 모델과 threshold를 한 번에 하나씩 변경합니다.
- 점수 향상이 없는 복잡도는 제거합니다.

완료 기준: holdout Page Hit@5와 MRR 목표를 만족하고 prepared latency 회귀가 허용 범위 안입니다.

## 5. Evidence와 Citation 정밀화

- 질문 개념을 직접 지지하는 Evidence만 답변에 포함합니다.
- 기관 간 비교 질문에서 각 주장에 서로 다른 문서 Citation을 강제합니다.
- 정답 외 페이지가 Citation에 포함되는 원인을 자동 분류합니다.
- 답변 보류 threshold를 새 데이터셋으로 다시 보정합니다.

완료 기준: Citation Precision과 Page Match Accuracy가 모두 기준을 통과하며 Unsafe Answer Rate가 0에 가깝게 유지됩니다.

## 6. 데모 전환과 정리

- [x] API와 Streamlit의 단일 문서 상수를 다중 문서 metadata로 교체합니다.
- [x] AI 보안 예시 질문을 제공합니다.
- [ ] 기관·언어·문서 필터를 제공합니다.
- [x] 새 코퍼스 검색 평가 결과를 README에 게시합니다.
- 필요성이 없는 옛 단일 문서 fixture와 이름을 제거합니다.

## 보류하는 항목

- MCP 서버
- Qdrant·OpenSearch·PostgreSQL·MinIO 운영
- 문서 업로드·사용자 권한 관리
- OCR과 복잡한 표 파싱
- 외부 LLM 기반 생성 답변

이 항목들은 현재 평가에서 명확한 문제를 해결하거나 실제 배포 요구가 생길 때 별도 ADR과 함께 검토합니다.
