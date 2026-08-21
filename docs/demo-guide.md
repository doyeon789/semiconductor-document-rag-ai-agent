# Local Demo Guide

## 1. 데모 범위

Streamlit과 FastAPI는 KISA·NIST·OWASP의 검증된 PDF 6개를 한 인덱스에서 검색합니다. 답변·Citation·Agent trace를 표시하고 Citation 링크는 해당 기관의 실제 로컬 PDF 페이지를 엽니다.

현재 답변은 외부 LLM이 아니라 PDF 원문 문장을 추출해 구성하므로 API key가 필요하지 않습니다.

## 2. 준비

```powershell
uv sync --frozen
.\.venv\Scripts\python.exe scripts\download_corpus.py --all
```

기본값은 다음과 같습니다.

```text
CORPUS_CATALOG_PATH=data/corpus/sources.yaml
CORPUS_PDF_DIR=data/raw/ai-security
```

다른 catalog나 PDF 디렉터리를 사용할 때만 `.env.example`을 참고해 환경 변수를 변경합니다. PDF와 `.env`는 커밋하지 않습니다.

## 3. 실행

첫 번째 PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload
```

두 번째 PowerShell:

```powershell
.\.venv\Scripts\python.exe -m streamlit run apps\ui\main.py
```

브라우저에서 `http://127.0.0.1:8501`을 엽니다. API 주소가 다르면 UI 왼쪽의 FastAPI 주소 또는 `RAG_API_BASE_URL`을 변경합니다.

## 4. 확인 항목

1. API `/docs`와 `/health/live`가 열립니다.
2. `AI 레드티밍` BM25 검색에서 KISA 레드티밍 가이드가 반환됩니다.
3. 검색 결과가 실제 source ID·문서명·기관·언어·버전을 포함합니다.
4. 일반 RAG가 원문 발췌와 Citation을 반환하거나 근거 부족으로 보류합니다.
5. Agentic RAG가 검색 모드, 재검색 여부와 종료 이유를 trace로 표시합니다.
6. Citation 링크가 올바른 문서의 같은 물리 페이지를 엽니다.

추천 질문:

```text
AI 보안 위협 대응 절차는 무엇인가?
AI 레드티밍 수행 시 고려할 항목은 무엇인가?
NIST AI RMF에서 GOVERN은 어떤 역할을 하는가?
```

## 5. Cold-start 준비

BM25는 바로 사용할 수 있지만 Dense와 Reranker는 첫 요청에서 모델과 1,282개 Chunk embedding을 준비합니다. Windows CPU 환경에서는 Agent의 기본 45초 tool timeout을 넘길 수 있습니다.

Agent 데모 전에 API 프로세스를 유지한 상태로 `/v1/search`에 `mode=rerank` 요청을 한 번 보내 준비합니다. 준비가 끝난 뒤 같은 프로세스의 요청은 만든 index를 재사용합니다.

```powershell
$body = @{
  query = "AI 레드티밍"
  mode = "rerank"
  top_k = 3
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/search" `
  -ContentType "application/json" `
  -Body $body
```

## 6. 알려진 제한

- 문서 선택·기관·언어 필터 UI가 없습니다.
- 원문 PDF 페이지의 문장 highlight를 지원하지 않습니다.
- 답변은 외부 LLM이 아닌 원문 발췌입니다.
- 네이티브 텍스트가 없는 페이지를 OCR하지 않습니다.
- 첫 Dense/Rerank 준비는 CPU에서 느리고 Agent timeout으로 종료될 수 있습니다.
- AI 보안 gold page 평가셋이 아직 없어 새 코퍼스의 품질 점수는 게시하지 않습니다.
