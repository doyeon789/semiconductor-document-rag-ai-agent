# Local Demo Guide

## 1. 데모 범위

Streamlit UI는 FastAPI를 통해 고정된 로컬 반도체 공정 PDF 한 개를 질문한다. UI는 별도의 검색·답변 로직을 갖지 않으며 다음 결과를 표시한다.

- 일반 RAG 또는 Agentic RAG 답변
- 답변을 구성한 원문 인용과 PDF 페이지 링크
- 답변 보류 및 API 오류 상태
- Agent의 검색 방식, 종료 이유와 실행 trace

현재 답변 생성은 외부 LLM이 아니라 PDF 원문 문장을 추출하는 방식이다. 따라서 API key나 LLM secret은 필요하지 않다.

## 2. 준비

Python 3.11 이상 환경에서 잠금 파일 기준 의존성을 설치한다.

```powershell
.\.venv\Scripts\uv.exe sync --frozen
```

기본 PDF를 다음 위치에 둔다.

```text
output/pdf/semiconductor_8_processes_chunking_guide_ko_v1_3.pdf
```

다른 위치를 사용하려면 `.env.example`을 참고해 현재 셸에 `DOCUMENT_PDF_PATH`를 설정한다. PDF와 `.env`는 Git에 커밋하지 않는다.

## 3. 실행

첫 번째 터미널에서 FastAPI를 실행한다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload
```

두 번째 터미널에서 Streamlit을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run apps\ui\main.py
```

브라우저에서 `http://127.0.0.1:8501`을 연다. API가 다른 주소에서 실행된다면 UI 왼쪽의 `FastAPI 주소`를 변경하거나 `RAG_API_BASE_URL` 환경 변수를 설정한다.

## 4. 확인 순서

1. 예시 질문을 선택하거나 직접 질문을 입력한다.
2. `Agentic RAG`를 선택한다.
3. `문서에서 답변 찾기`를 누른다.
4. 답변과 종료 상태, 검색 경로를 확인한다.
5. Citation의 `PDF p.N` 링크를 눌러 원문 페이지를 확인한다.
6. Agent 실행 경로에서 최초 검색과 필요 시 재검색이 수행됐는지 확인한다.

추천 질문:

```text
산화 공정에서 형성되는 막은 무엇인가?
습식 산화와 건식 산화의 차이는 무엇인가?
포토 공정의 주요 단계를 설명해줘.
```

## 5. 알려진 제한

- 문서 업로드와 문서 목록 관리는 지원하지 않는다.
- 원문 PDF 페이지는 새 브라우저 탭에서 열리며 문장 highlight는 지원하지 않는다.
- 답변은 생성형 LLM 문장이 아니라 선택된 원문 발췌다.
- 첫 Dense 또는 Rerank 요청은 로컬 모델 준비 때문에 느릴 수 있다.
- 검색된 페이지가 정답 페이지인지 판단하는 정확도와 답변 보류 기준은 Day 9·11에서 개선한다.
