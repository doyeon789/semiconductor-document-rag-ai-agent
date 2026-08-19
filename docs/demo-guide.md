# Local Demo Guide

## 1. 현재 데모의 의미

현재 Streamlit과 FastAPI는 **설정한 로컬 PDF 한 개**를 대상으로 검색·답변·Citation·Agent trace를 확인하는 기능 스모크 테스트입니다.

AI 보안 PDF 6종의 다운로드와 검증은 완료했지만, 문서별 metadata와 다중 문서 인덱스는 아직 API에 연결되지 않았습니다. 따라서 현재 UI를 최종 AI 보안 데모나 새 코퍼스 성능 평가로 사용하지 않습니다.

## 2. 준비

```powershell
uv sync --frozen
.\.venv\Scripts\python.exe scripts\download_corpus.py --all
```

`.env.example`을 참고해 현재 PowerShell 세션의 `DOCUMENT_PDF_PATH`를 테스트할 PDF로 설정합니다. PDF와 `.env`는 커밋하지 않습니다.

```powershell
$env:DOCUMENT_PDF_PATH = "data/raw/ai-security/kisa_ai_security_guide_ko_2026_corrected.pdf"
```

주의: 현재 API의 문서 ID·제목은 단일 문서 상수로 남아 있으므로 새 PDF를 지정해도 표시 metadata는 정확하지 않습니다. 이 단계에서는 검색 파이프라인 동작만 확인합니다.

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
2. BM25 검색이 페이지 결과를 반환합니다.
3. Dense·Hybrid·Rerank 첫 실행 후 모델 cache가 생성됩니다.
4. 일반 RAG가 원문 발췌와 Citation을 반환하거나 근거 부족으로 보류합니다.
5. Agentic RAG가 검색 모드, 재검색 여부와 종료 이유를 trace로 표시합니다.
6. Citation 링크가 PDF의 같은 물리 페이지를 엽니다.

AI 보안 문서를 임시로 테스트한다면 해당 문서에 실제 존재하는 용어를 질문합니다. 예:

```text
AI 보안 위협 대응 절차는 무엇인가?
레드티밍 수행 시 고려할 항목은 무엇인가?
AI 위험관리에서 측정은 어떤 역할을 하는가?
```

표시된 문서 제목은 현재 정확하지 않을 수 있으므로 검색된 원문과 페이지 확인에만 사용합니다.

## 5. 알려진 제한

- PDF 한 개만 인덱싱합니다.
- 문서 ID·제목과 PDF 경로가 아직 매니페스트에서 함께 로드되지 않습니다.
- PDF 업로드와 문서 선택 UI가 없습니다.
- 원문 페이지 highlight를 지원하지 않습니다.
- 답변은 외부 LLM이 아닌 원문 발췌입니다.
- 네이티브 텍스트가 없는 페이지를 OCR하지 않습니다.
- 첫 Dense/Rerank 요청은 모델 준비로 느릴 수 있습니다.

다음 작업은 6개 문서를 한 서비스에 연결하고 UI 예시·필터·Citation metadata를 실제 AI 보안 코퍼스로 교체하는 것입니다.
