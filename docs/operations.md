# Operations Guide

## 1. 운영 범위

현재 운영 대상은 Windows 로컬 개발, GitHub Actions CI와 포트폴리오용 단일 프로세스 데모입니다. 별도 DB, vector database, keyword search cluster, object storage나 MCP 서버는 실행하지 않습니다.

## 2. 로컬 구성

| 프로세스 | 기본 주소 | 역할 |
| --- | --- | --- |
| FastAPI | `http://127.0.0.1:8000` | 검색·답변·Agent·PDF endpoint |
| Streamlit | `http://127.0.0.1:8501` | 질문과 Citation 확인 UI |

모델 cache, 원본 PDF, 인덱스와 평가 출력은 모두 로컬에 있고 Git에서 제외됩니다.

## 3. 환경 변수

| 변수 | 필수 | 역할 |
| --- | :---: | --- |
| `APP_ENV` | 아니요 | 현재 실행 환경 표시 |
| `LOG_LEVEL` | 아니요 | 로그 수준 |
| `DOCUMENT_PDF_PATH` | 데모 시 | 현재 단일 문서 PDF 경로 |
| `RERANKER_MODEL` | 아니요 | FastEmbed Cross-Encoder 모델명 |
| `RAG_API_BASE_URL` | 아니요 | Streamlit이 호출할 FastAPI 주소 |

현재 답변은 외부 LLM을 호출하지 않으므로 API key가 필요하지 않습니다.

## 4. 준비와 실행

```powershell
uv sync --frozen

# 코퍼스 확보
.\.venv\Scripts\python.exe scripts\download_corpus.py --all

# API
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload

# 별도 터미널에서 UI
.\.venv\Scripts\python.exe -m streamlit run apps\ui\main.py
```

다중 문서 연결 전에는 `DOCUMENT_PDF_PATH`가 가리키는 한 파일만 인덱싱합니다. 새 코퍼스 전체 데모로 오해하지 않도록 합니다.

## 5. Health와 준비 상태

`GET /health/live`는 API 프로세스가 응답하는지만 확인합니다. PDF 존재, parser와 검색 모델 준비를 확인하는 별도 readiness endpoint는 아직 없습니다.

실질적인 준비 확인:

1. `scripts/download_corpus.py --all`이 6개 문서에 대해 `existing` 또는 `downloaded`를 반환합니다.
2. API 시작 후 `/docs`가 열립니다.
3. `POST /v1/search`의 `bm25` 요청이 성공합니다.
4. `rerank` 첫 요청에서 모델을 준비한 뒤 결과가 반환됩니다.
5. Citation PDF 링크가 실제 페이지를 엽니다.

## 6. 첫 요청과 모델 cache

Dense와 Reranker는 지연 로드하므로 첫 요청은 모델 다운로드·초기화 때문에 느릴 수 있습니다.

- cache 위치: `indexes/models/`
- 성능 측정: 첫 요청과 warm 요청을 분리
- CI/unit test: fake model을 사용해 네트워크 의존성 제거
- 모델을 바꾸면 모델명과 평가 결과를 함께 기록

## 7. 자주 발생하는 문제

### PDF를 찾지 못함

- `DOCUMENT_PDF_PATH`가 현재 PowerShell 작업 디렉터리 기준으로 유효한지 확인합니다.
- 코퍼스 문서는 `data/raw/ai-security/`에 있습니다.
- PDF는 Git clone만으로 제공되지 않으므로 다운로드 명령을 먼저 실행합니다.

### 코퍼스 해시 불일치

- 공식 파일이 변경됐을 수 있으므로 landing page와 게시일을 확인합니다.
- 기대 해시를 임의로 바꾸지 말고 새 버전인지 검토합니다.
- 문제가 있는 로컬 파일 하나만 다시 받으려면 source ID와 `--overwrite`를 사용합니다.

### 첫 Dense/Rerank 요청이 느림

- 모델 cache가 처음 생성되는 정상 동작인지 확인합니다.
- 실제 latency 비교는 준비 요청 후 측정합니다.
- 모델 다운로드 실패 시 네트워크와 cache 쓰기 권한을 확인합니다.

### 잘못된 Citation 페이지

1. SearchHit의 `version_id`, `page_start`, `page_end`를 확인합니다.
2. Evidence의 문서 ID와 페이지를 확인합니다.
3. PDF의 물리 페이지와 UI의 `#page=N`을 대조합니다.
4. 0-based/1-based 변환이 추가되지 않았는지 확인합니다.
5. 실패 질문을 평가 case와 regression test로 추가합니다.

### Agent가 종료되지 않음

- `max_steps`, `max_retrieval_attempts`, `max_repair_attempts`가 요청 범위 안인지 확인합니다.
- trace에서 같은 query가 반복되는지 확인합니다.
- tool timeout과 종료 이유를 확인합니다.

## 8. CI와 릴리스 확인

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src scripts\download_corpus.py
```

릴리스 전에는 새 AI 보안 평가셋 결과, 알려진 제한, 코퍼스 출처와 재배포 조건을 다시 확인합니다. 현재는 다중 문서 전환 중이므로 새 코퍼스 기준 릴리스 점수를 게시하지 않습니다.
