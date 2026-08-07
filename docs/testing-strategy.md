# Testing Strategy

## 1. 목표

외부 LLM과 검색 서비스의 비결정성을 격리하고, 페이지 추적·검색·인용·Agent routing의 핵심 불변식을 자동으로 검증한다.

## 2. Test Layers

| Layer | 대상 | 외부 의존성 |
| --- | --- | --- |
| Unit | 정규화, Chunking, Fusion, sufficiency, routing policy | 없음 |
| Component | parser adapter, repository, search adapter, prompt builder | container 또는 fixture |
| Contract | REST schema, MCP tool schema, adapter port | mock server/real serialization |
| Integration | PostgreSQL, Qdrant, OpenSearch, MinIO 연동 | Docker Compose |
| Evaluation | retrieval, answer, citation, trajectory 지표 | 고정 dataset/model |
| End-to-End | upload → index → question → citation page | 전체 stack |

## 3. Unit Test Matrix

### Ingestion

- Unicode와 단위 정규화
- 페이지 번호 0/1-based 변환 금지
- 문단·목록 경계 Chunking
- 페이지 경계 Chunking
- 표 행 serialization
- 반복 header/footer 제외
- idempotency key 안정성

### Retrieval

- RRF 계산과 tie breaking
- Dense/BM25 후보 deduplication
- 문서별 diversity 규칙
- glossary expansion과 모호한 약어 처리
- filter propagation
- sufficiency 상태 결정

### Citation

- quote가 올바른 페이지에 존재
- stale version 거부
- unsupported claim 탐지
- contradicting evidence 표시
- 다중 Citation coverage

### Agent

- 모든 routing condition
- retry/step limit
- tool error budget
- answer repair 한도
- 정상 abstention

## 4. Fixtures

```text
tests/fixtures/
├── pdf/
│   ├── text_en_two_column.pdf
│   ├── text_ko.pdf
│   ├── scanned_ko_en.pdf
│   ├── table_single_page.pdf
│   ├── table_multi_page.pdf
│   ├── repeated_header_footer.pdf
│   └── malformed.pdf
├── parsed/
│   ├── elements.jsonl
│   └── tables.jsonl
├── retrieval/
│   ├── candidates.json
│   └── expected_rrf.json
├── agent/
│   └── tool_responses.json
└── api/
    └── responses.json
```

Fixture 문서는 재배포 권한을 확인하고 [Data Policy](./data-policy.md)에 출처와 라이선스를 기록한다.

## 5. Golden Tests

- parser 결과 전체를 그대로 비교하기보다 안정적인 필드를 선택한다.
- page count, element type/order, 핵심 text, table cell, Chunk page range를 검증한다.
- parser library version 변경 시 golden diff를 사람이 확인한다.
- OCR text는 허용 edit distance 또는 핵심 token 보존으로 비교할 수 있다.

## 6. Mocking Policy

- Domain unit test에서 외부 SDK를 import하지 않는다.
- LLM은 schema-valid canned response 또는 deterministic fake를 사용한다.
- Qdrant/OpenSearch repository unit test는 port fake를 사용한다.
- 실제 query 문법과 mapping은 container integration test에서 검증한다.
- MCP contract test는 JSON 직렬화와 typed error를 실제로 검증한다.

## 7. Integration Environments

### Fast CI

- unit
- contract
- parser fixture 일부
- lint/type check

### Full CI / Nightly

- Docker Compose integration
- 모든 PDF fixture
- retrieval evaluation development split
- Agent trajectory tests
- E2E smoke test

API 비용이 발생하는 test는 명시적인 marker와 예산 제한을 사용한다.

```text
pytest -m "not external"
pytest -m integration
pytest -m evaluation
pytest -m external
```

## 8. Required E2E Scenarios

1. 텍스트 PDF 등록 → READY → 검색 → 올바른 페이지
2. 스캔 PDF 등록 → OCR 사용 확인 → 검색
3. 표 PDF 등록 → table query → 올바른 row/page
4. 문서 2개 등록 → comparison answer → 문서별 Citation
5. 답변 불가능 질문 → 정상 abstention
6. 잘못된 page reference → Citation validation 실패
7. Qdrant 장애 → BM25 fallback
8. OpenSearch 장애 → Dense fallback
9. 두 backend 장애 → tool error 후 abstention
10. 동일 PDF 재등록 → 중복 색인 없음

## 9. Traceability

테스트 이름 또는 marker에 요구사항 ID를 포함한다.

```python
def test_fr_ing_002_preserves_pdf_page_number(): ...
def test_fr_ans_005_abstains_without_evidence(): ...
```

Release 전에 다음 matrix를 생성한다.

| Requirement | Unit | Integration | Evaluation | E2E |
| --- | :---: | :---: | :---: | :---: |
| FR-ING-002 | ✓ | ✓ |  | ✓ |
| FR-RET-003 | ✓ | ✓ | ✓ | ✓ |
| FR-ANS-005 | ✓ |  | ✓ | ✓ |
| FR-AGT-003 | ✓ | ✓ | ✓ | ✓ |

## 10. Quality Gates

PR gate:

- Ruff format/check 통과
- mypy 통과
- unit/contract test 통과
- 새 기능의 요구사항 ID와 test 존재
- migration 또는 schema 변경 문서화

Release gate:

- integration/E2E 통과
- evaluation MVP gate 통과
- critical/high severity 알려진 결함 없음
- Docker clean start smoke test 통과
- 데이터·secret 검사 통과

## 11. Flaky Test Policy

- 실패한 test를 무조건 재시도해 통과시키지 않는다.
- 외부 의존성 test만 제한된 retry를 허용한다.
- flaky test는 issue를 생성하고 owner와 제거 기한을 기록한다.
- 평가 threshold 근처의 비결정성은 seed, temperature, judge variation을 함께 기록한다.

## 12. 관련 문서

- [Evaluation Plan](./evaluation-plan.md)
- [Ingestion Design](./ingestion-design.md)
- [Operations](./operations.md)

