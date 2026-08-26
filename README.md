<div align="center">

# AI Security Document RAG

### Public AI security guidance, retrieved with page-grounded evidence

KISA·NIST·OWASP의 공개 AI 보안 문서를 검색하고<br>
**문서명·PDF 페이지·원문 인용과 함께 답변하는 로컬 Agentic RAG**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Status](https://img.shields.io/badge/Status-Evaluation%20Baseline-F59E0B)
![Retrieval](https://img.shields.io/badge/Retrieval-BM25%20%2B%20Dense%20%2B%20Rerank-2563EB)
![License](https://img.shields.io/badge/Code%20License-MIT-22C55E)

</div>

## 프로젝트 목표

AI 보안 지침은 기관과 버전마다 용어와 권고 범위가 다릅니다. 이 프로젝트는 여러 공식 PDF에서 질문과 관련된 페이지를 찾고, 답변의 모든 근거를 사용자가 원문에서 다시 확인할 수 있게 만드는 것을 목표로 합니다.

핵심 원칙은 세 가지입니다.

1. **검색 품질 우선** — BM25, Dense, Hybrid, Cross-Encoder Reranking을 같은 평가셋에서 비교합니다.
2. **페이지 근거 보존** — 모든 검색 결과와 답변 인용을 실제 PDF 페이지로 추적합니다.
3. **안전한 답변 보류** — 충분한 근거가 없으면 추측하지 않고 답변을 보류합니다.

## 현재 상태

| 영역 | 상태 |
| --- | --- |
| 공개 코퍼스 출처·버전·라이선스 기록 | 완료 |
| KISA·NIST·OWASP PDF 6종 자동 다운로드와 SHA-256 검증 | 완료 |
| PyMuPDF 페이지 추출과 페이지 단위 Chunk | 완료 |
| 원문과 분리된 보수적 절 문맥 검색 | 완료 |
| 로컬 BM25·Dense·Hybrid·Rerank 검색 | 완료 |
| 원문 발췌 답변·Citation 검증·답변 보류 | 완료 |
| LangGraph 기반 제한된 재검색과 실행 trace | 완료 |
| 6개 문서 통합 인덱싱과 문서별 메타데이터 연결 | 완료 |
| AI 보안 질문 평가셋과 새 검색 성능 기준 | 완료 |

현재 API와 UI는 검증된 6개 PDF를 한 인덱스에서 검색합니다. 각 검색 결과와 Citation은 실제 source ID·문서명·기관·언어·버전·PDF 페이지를 보존합니다. AI 보안 검색 기준선은 별도의 development 30문항과 holdout 15문항에서 `document_id + page_number`를 정답 단위로 측정합니다.

## 공개 AI 보안 코퍼스

| 문서 | 기관 | 언어 | 이용 조건 |
| --- | --- | --- | --- |
| [인공지능(AI) 보안 안내서 정오 수정본](https://www.kisa.or.kr/2060204/form?lang_type=KO&page=13&postSeq=19) | KISA | 한국어 | 재배포 전 조건 확인 |
| [AI 보안 위협 대응 매뉴얼](https://www.kisa.or.kr/401/form?lang_type=KO&postSeq=3712) | KISA | 한국어 | 재배포 전 조건 확인 |
| [AI 보안 레드티밍 가이드](https://www.kisa.or.kr/401/form?page=1&postSeq=3713) | KISA | 한국어 | 재배포 전 조건 확인 |
| [AI Risk Management Framework 1.0](https://doi.org/10.6028/NIST.AI.100-1) | NIST | 영어 | 출처 표기 |
| [Generative AI Profile](https://doi.org/10.6028/NIST.AI.600-1) | NIST | 영어 | 출처 표기 |
| [GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) | OWASP | 영어 | CC BY-SA 4.0 |

기계 판독 가능한 출처 정보는 [`data/corpus/sources.yaml`](./data/corpus/sources.yaml)에 있습니다. 2026-08-21 로더 검증에서 6개 문서 총 773쪽 중 표지·이미지 목차·장 구분 간지·공백 16쪽을 제외한 757쪽을 1,282개 페이지 추적 Chunk로 구성했습니다.

## AI 보안 검색 기준선

2026-08-24, development는 commit `5c49c76`, dev와 정답 페이지를 완전히 분리한 holdout은 commit `fe97086`에서 측정했습니다. Top-5, 동일한 1,282개 Chunk와 Windows CPU 환경이며 development 결과로 Dense를 선택한 후 holdout에는 Dense만 적용했습니다. latency는 현재 개발 환경의 비교값입니다.

| Split·모드 | Page Hit@5 | Document Coverage@5 | Recall@5 | MRR | prepared p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| development · BM25 | 0.700 | 0.733 | 0.683 | 0.575 | 41.94 ms |
| development · Dense | **0.767** | **0.833** | **0.700** | 0.552 | 337.40 ms |
| development · Hybrid | 0.733 | 0.733 | 0.683 | **0.631** | 463.27 ms |
| development · Rerank | 0.733 | 0.750 | **0.700** | 0.598 | 23,878.46 ms |
| holdout · Dense | 0.467 | 0.867 | 0.433 | 0.283 | 394.16 ms |

전체 질문의 평균 문서 커버리지는 높지만 기관 간 비교 질문만 보면 Dense가 필요한 문서를 모두 찾은 경우는 development 0/4, holdout 1/3입니다. 정확한 페이지 순위와 다중 문서 회수, 한영 교차 검색이 모두 병목입니다. Rerank는 개발셋 정확도를 개선하지 못하면서 질문당 약 20초가 걸렸습니다. 따라서 현재 기준선은 품질 Gate를 통과한 최종 성능이 아니라 다음 개선이 넘어야 할 출발점입니다.

### 보수적 절 문맥 실험

2026-08-25 commit `eed40db`에서 원문 Chunk 경계는 그대로 두고, 제목이 빠진 같은 페이지의 후속 Chunk 42개에만 짧은 영문 2단계 절 제목 또는 NIST function 표 제목을 검색 입력으로 보강했습니다. BM25·Dense·Reranker만 검색 전용 `retrieval_text`를 사용하고 Evidence·Citation·API는 계속 원문 `text`를 사용합니다.

| Split | Page Hit@5 | Document Coverage@5 | Recall@5 | MRR | NDCG@5 | prepared p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| development · baseline → section context | 0.767 → 0.767 | 0.833 → 0.833 | 0.700 → 0.700 | 0.552 → **0.559** | 0.566 → **0.572** | 337.40 → 326.66 ms |
| holdout · baseline → section context | 0.467 → 0.467 | 0.867 → 0.867 | 0.433 → 0.433 | 0.283 → 0.283 | 0.314 → 0.309 | 394.16 → 337.90 ms |

Development에서는 정답 순위 두 건이 `3→2`, `5→4`로 올라갔고 하락한 정답 순위는 없었습니다. 동결된 holdout의 주요 지표와 첫 정답 1위는 그대로였지만, 한 문항의 두 번째 정답 페이지가 `2→3`위로 내려가 NDCG@5가 0.005 낮아졌습니다. 따라서 이 변경은 원문 근거를 훼손하지 않는 작은 개선으로 유지하지만, 전체 Chunk 구조 개선 Gate를 통과한 것으로 보지는 않습니다.

## 시작하기

Windows PowerShell 기준입니다.

```powershell
uv sync --frozen

# 코퍼스 목록과 정책 확인
.\.venv\Scripts\python.exe scripts\download_corpus.py --list

# 공식 PDF 6종 다운로드 및 해시 검증
.\.venv\Scripts\python.exe scripts\download_corpus.py --all
```

PDF는 Git에서 제외된 `data/raw/ai-security/`에 저장되고, 다운로드 URL·시각·파일 크기·SHA-256은 같은 디렉터리의 `download_receipt.json`에 기록됩니다.

기본 catalog와 PDF 디렉터리는 `.env.example`에 기록되어 있으며 필요할 때 `CORPUS_CATALOG_PATH`와 `CORPUS_PDF_DIR`로 변경할 수 있습니다.

```powershell
# Terminal 1
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload

# Terminal 2
.\.venv\Scripts\python.exe -m streamlit run apps\ui\main.py
```

브라우저에서 `http://127.0.0.1:8501`을 엽니다. 제한 사항은 [Local Demo Guide](./docs/demo-guide.md)에 정리되어 있습니다.

## 현재 검색 흐름

```text
공식 PDF 6종
  → PyMuPDF 네이티브 텍스트 추출
  → 물리 페이지 단위 Chunk
  → 같은 페이지의 검색 전용 절 문맥 보강
  → BM25 + 다국어 Dense 검색
  → Reciprocal Rank Fusion
  → 다국어 Cross-Encoder Reranking
  → Evidence 선택과 충분성 판정
  → 실제 문서명·원문 발췌·페이지 Citation 또는 답변 보류
```

외부 LLM은 현재 답변 생성에 사용하지 않습니다. 답변은 검색된 PDF의 원문 문장을 추출해 구성하므로 API 키가 필요하지 않습니다.

## 품질 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy apps src tests scripts\evaluate_retrieval.py scripts\evaluate_rag.py

# development에서 네 검색 모드 비교
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py

# 선택된 Dense를 동결된 holdout에 적용
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py `
  --dataset data\evaluation\ai_security_retrieval_holdout.json `
  --modes dense
```

기존 단일 문서 평가 결과는 회귀 비교용으로만 보존합니다. 새 AI 보안 평가 질문과 정답 페이지는 [`data/evaluation`](./data/evaluation)에 있으며, 상세한 측정 조건과 다음 성능 작업은 [Evaluation Plan](./docs/evaluation-plan.md)과 [Roadmap](./docs/roadmap.md)을 참고하세요.

## 문서와 저작권

- 전체 문서 목차: [docs/README.md](./docs/README.md)
- 데이터 정책: [docs/data-policy.md](./docs/data-policy.md)
- 코퍼스 출처: [data/corpus/sources.yaml](./data/corpus/sources.yaml)

이 저장소에는 외부 PDF 원본을 커밋하지 않습니다. 코드의 [MIT License](./LICENSE)는 KISA·NIST·OWASP 문서의 이용 권한을 대신하지 않습니다.
