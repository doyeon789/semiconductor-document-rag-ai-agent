"""Render the local Semiconductor RAG Streamlit demo."""

from __future__ import annotations

import os

import streamlit as st
from pydantic import ValidationError

from apps.ui.client import RagApiClient, RagApiError
from apps.ui.presentation import DemoResult, build_demo_result

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
EXAMPLE_QUESTIONS = (
    "산화 공정에서 형성되는 막은 무엇인가?",
    "습식 산화와 건식 산화의 차이는 무엇인가?",
    "포토 공정의 주요 단계를 설명해줘.",
)


def main() -> None:
    """Render inputs, run one API request, and show grounded evidence."""
    st.set_page_config(
        page_title="Semiconductor RAG Demo",
        page_icon="🔬",
        layout="wide",
    )
    _render_theme()
    st.markdown("# Semiconductor Document RAG")
    st.caption("반도체 공정 PDF에서 페이지 근거를 찾아 답변하는 Agentic RAG 데모")

    api_url, agentic, top_k, max_claims, show_trace = _render_sidebar()
    _render_examples()
    question = st.text_area(
        "질문",
        key="question",
        height=110,
        placeholder="반도체 공정 문서에 대해 질문해 주세요.",
    )
    submitted = st.button("문서에서 답변 찾기", type="primary", width="stretch")
    if submitted:
        _run_question(api_url, question, agentic, top_k, max_claims)

    result = st.session_state.get("demo_result")
    if isinstance(result, DemoResult):
        _render_result(result, RagApiClient(api_url), show_trace)
    else:
        _render_empty_state()


def _render_sidebar() -> tuple[str, bool, int, int, bool]:
    """Render runtime settings in the sidebar.

    Returns
    -------
    tuple[str, bool, int, int, bool]
        API URL, Agent mode, retrieval limit, claim limit, and trace visibility.
    """
    with st.sidebar:
        st.header("실행 설정")
        api_url = st.text_input(
            "FastAPI 주소",
            value=os.getenv("RAG_API_BASE_URL", DEFAULT_API_BASE_URL),
        )
        mode = st.radio(
            "답변 방식",
            ("Agentic RAG", "일반 RAG"),
            help="Agentic RAG는 근거가 부족하면 검색어를 바꾸고 다시 검색합니다.",
        )
        top_k = st.slider("검색 결과 수", 1, 10, 5)
        max_claims = st.slider("최대 답변 근거 수", 1, 3, 2)
        show_trace = st.toggle("Agent 실행 경로 표시", value=True)
        st.divider()
        st.info(
            "현재 답변은 외부 LLM 없이 PDF 원문을 추출해 구성합니다. "
            "모든 Citation은 원문 페이지와 대조됩니다."
        )
    return api_url, mode == "Agentic RAG", top_k, max_claims, show_trace


def _render_examples() -> None:
    """Render buttons that fill the question input with demo prompts."""
    st.markdown("#### 예시 질문")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for column, question in zip(columns, EXAMPLE_QUESTIONS, strict=True):
        if column.button(question, width="stretch"):
            st.session_state.question = question
            st.rerun()


def _run_question(
    api_url: str,
    question: str,
    agentic: bool,
    top_k: int,
    max_claims: int,
) -> None:
    """Call the selected answer endpoint and retain its presentation model.

    Parameters
    ----------
    api_url : str
        FastAPI origin entered by the user.
    question : str
        Question currently entered in the text area.
    agentic : bool
        Whether to call the Agent endpoint.
    top_k : int
        Maximum retrieved evidence count.
    max_claims : int
        Maximum answer claim count.
    """
    try:
        client = RagApiClient(api_url)
        with st.spinner("PDF 근거를 검색하고 Citation을 검증하고 있습니다..."):
            api_result = client.ask(
                question,
                agentic=agentic,
                top_k=top_k,
                max_claims=max_claims,
            )
        st.session_state.demo_result = build_demo_result(api_result, agentic=agentic)
    except (RagApiError, ValidationError, ValueError) as exc:
        st.session_state.pop("demo_result", None)
        st.error(str(exc))


def _render_result(result: DemoResult, client: RagApiClient, show_trace: bool) -> None:
    """Render answer status, citations, and optional Agent trajectory.

    Parameters
    ----------
    result : DemoResult
        Normalized response from the API.
    client : RagApiClient
        Client used to construct original PDF page links.
    show_trace : bool
        Whether Agent trace events should be visible.
    """
    st.divider()
    status_column, latency_column, route_column = st.columns(3)
    status_column.metric("종료 상태", result.termination_reason)
    latency_column.metric("응답 시간", f"{result.elapsed_ms / 1_000:.2f}초")
    route_text = " → ".join(result.search_modes) if result.search_modes else "rerank"
    route_column.metric("검색 경로", route_text)

    if result.abstained:
        st.warning(
            result.abstention_message or "문서에서 충분한 근거를 찾지 못했습니다."
        )
    else:
        st.markdown("## 답변")
        st.markdown(result.answer or "")
        st.markdown("## 출처")
        for index, citation in enumerate(result.citations, start=1):
            page_url = client.document_pdf_url(
                citation.document_id,
                citation.page_number,
            )
            with st.container(border=True):
                st.markdown(
                    f"**{index}. {citation.document_title} · "
                    f"[PDF p.{citation.page_number}]({page_url})**"
                )
                st.caption(citation.quote)

    if result.tool_errors:
        st.error("도구 오류: " + ", ".join(result.tool_errors))
    if show_trace and result.trace:
        st.markdown("## Agent 실행 경로")
        st.dataframe(
            [event.model_dump() for event in result.trace],
            column_config={
                "sequence": "순서",
                "name": "이벤트",
                "mode": "검색 방식",
                "detail": "세부 정보",
            },
            hide_index=True,
            width="stretch",
        )


def _render_empty_state() -> None:
    """Explain the initial demo state before the first question."""
    st.markdown(
        """
        <div class="empty-state">
          <strong>질문을 입력하면 다음 결과를 확인할 수 있습니다.</strong><br/>
          문서 기반 답변 · 원문 PDF 페이지 · Citation · Agent 검색 경로
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_theme() -> None:
    """Apply a compact visual theme without external assets."""
    st.markdown(
        """
        <style>
        .stApp { background: #f7f9fc; }
        [data-testid="stSidebar"] { background: #edf3f8; }
        .block-container { max-width: 1120px; padding-top: 2.5rem; }
        .empty-state {
            margin-top: 1.5rem;
            padding: 2.2rem;
            border: 1px dashed #94a3b8;
            border-radius: 16px;
            background: #ffffff;
            color: #334155;
            text-align: center;
            line-height: 1.8;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
