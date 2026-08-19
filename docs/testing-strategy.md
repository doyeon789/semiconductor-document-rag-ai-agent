# Testing Strategy

## 1. 목표

외부 LLM과 서버 없이 페이지 추적, 검색 순위, Citation, 답변 보류와 Agent 종료 조건을 결정적으로 검증합니다.

## 2. 현재 테스트 계층

| 계층 | 대상 |
| --- | --- |
| Unit | 도메인 모델, PDF text normalization, Chunking, BM25, Dense, RRF, Rerank, Evidence, 답변, Agent routing |
| Integration | 실제 로컬 PDF를 사용한 페이지 추출·Chunk 생성 |
| API/UI | FastAPI endpoint, 응답 schema, PDF 링크와 Streamlit presentation |
| Evaluation | 검색 지표, 품질 지표, 오류 분석과 보고서 생성 |
| Corpus | 출처 YAML, URL, 해시, 다운로드 실패와 영수증 |

현재 CI는 Ruff, mypy와 pytest를 실행합니다. Docker나 외부 검색 서비스는 테스트 대상이 아닙니다.

## 3. 필수 불변식

### 코퍼스

- source ID와 filename이 중복되지 않습니다.
- 다운로드 URL은 HTTPS입니다.
- 기대 SHA-256은 64자 소문자 hex입니다.
- 제외 페이지는 양수·고유하며 문서 페이지 수를 넘지 않습니다.
- 다운로드 파일이 PDF가 아니거나 해시가 다르면 저장하지 않습니다.

### Ingestion

- PDF 페이지는 1부터 시작하고 원래 순서를 유지합니다.
- Element bbox와 읽기 순서가 유효합니다.
- Chunk page range가 실제 페이지 범위를 벗어나지 않습니다.
- 같은 입력으로 만든 ID와 content hash가 안정적입니다.

### Retrieval

- BM25, Dense, RRF tie-breaking이 결정적입니다.
- Hybrid 결과에서 같은 Chunk가 중복되지 않습니다.
- Reranker는 후보 수와 같은 개수의 점수를 반환해야 합니다.
- 각 SearchHit은 원본 version ID와 페이지를 유지합니다.

### Answer와 Agent

- Citation quote가 Evidence text에 정확히 존재합니다.
- 답변 보류에는 Claim과 Citation이 없습니다.
- 충분한 Evidence가 없는 경우 답변을 만들지 않습니다.
- Agent는 재검색·step·repair·timeout 상한을 지킵니다.
- 프롬프트 인젝션 입력은 tool 호출 전에 종료됩니다.
- trace만으로 검색 모드, 검색어와 종료 이유를 확인할 수 있습니다.

## 4. 다중 문서 전환 필수 테스트

1. 6개 문서의 페이지 수와 해시가 매니페스트와 일치합니다.
2. 모든 제외 페이지가 Chunk 인덱스에서 빠집니다.
3. 서로 다른 문서의 같은 페이지 번호가 별도 검색 결과로 유지됩니다.
4. SearchHit·Evidence·Citation의 source ID와 PDF 경로가 일치합니다.
5. 기관 필터와 언어 필터가 모든 검색 모드에 전달됩니다.
6. 비교 질문이 두 개 이상 필요한 문서의 Evidence를 포함합니다.
7. 없는 문서나 변조된 PDF가 부분 성공으로 숨겨지지 않습니다.

## 5. 명령

```powershell
# 전체 테스트
.\.venv\Scripts\python.exe -m pytest -q

# 포맷과 린트
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .

# 현재 애플리케이션과 코퍼스 스크립트 타입 검사
.\.venv\Scripts\python.exe -m mypy src scripts\download_corpus.py
```

전체 `scripts/` mypy는 별도 PDF 생성 유틸리티의 ReportLab type stub 문제와 섞일 수 있으므로, CI와 같은 범위를 기준으로 판단합니다.

## 6. 모델 테스트 원칙

- 기본 단위 테스트에서는 fake embedder와 fake reranker를 사용합니다.
- 실제 FastEmbed 모델 테스트는 모델 cache와 실행 시간을 고려해 명시적으로 실행합니다.
- 모델 변경은 새 AI 보안 평가셋 결과와 함께 검토합니다.
- threshold 근처의 결과를 단순 재시도로 통과시키지 않습니다.

## 7. PR Gate

- 변경 파일의 요구사항과 테스트가 일치합니다.
- pytest, Ruff와 적용 범위 mypy가 통과합니다.
- 외부 PDF·secret·model cache·평가 artifact가 Git에 없습니다.
- 문서의 현재/다음 상태가 실제 코드와 맞습니다.
