"""Create the HTTP API application and local document search contract."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.agent import (
    AgentRun,
    LocalRetrievalAgentTools,
    RetrievalAgent,
)
from semiconductor_rag.answering import (
    AbstentionReason,
    EvidenceSufficiency,
    GroundedCitation,
    GroundedClaim,
    TerminationReason,
    build_evidence_pack,
    build_grounded_answer,
)
from semiconductor_rag.ingestion import (
    PdfExtractionError,
    build_page_chunks,
    extract_pdf,
)
from semiconductor_rag.retrieval import (
    DEFAULT_RERANKER_MODEL,
    FastEmbedder,
    FastEmbedReranker,
    LocalSearchService,
    SearchMode,
)

DEFAULT_DOCUMENT_ID = "SEMI-8P-RAG-KO"
DEFAULT_DOCUMENT_VERSION = "1.3"
DEFAULT_DOCUMENT_TITLE = "반도체 8대 제조 공정: 웨이퍼에서 패키징까지"
DEFAULT_EXCLUDED_CORPUS_PAGES = frozenset({65})
DEFAULT_PDF_PATH = Path(
    "output/pdf/semiconductor_8_processes_chunking_guide_ko_v1_3.pdf"
)
DEFAULT_VERSION_ID = uuid5(
    NAMESPACE_URL,
    f"{DEFAULT_DOCUMENT_ID}:{DEFAULT_DOCUMENT_VERSION}",
)


class LiveHealthResponse(BaseModel):
    """Describe a live API process."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class SearchRequest(BaseModel):
    """Validate one local document search request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    mode: SearchMode = SearchMode.BM25
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResultResponse(BaseModel):
    """Describe one page-traceable ranked search result."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    chunk_id: UUID
    version_id: UUID
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text: str
    score: float


class SearchResponse(BaseModel):
    """Return ranked local search results and execution metadata."""

    model_config = ConfigDict(extra="forbid")

    query_id: UUID
    document_id: str
    mode: SearchMode
    embedding_model: str | None
    reranker_model: str | None
    results: list[SearchResultResponse]
    latency_ms: float = Field(ge=0)


class AnswerRequest(BaseModel):
    """Validate one page-grounded answer request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    max_claims: int = Field(default=1, ge=1, le=3)


class AnswerResponse(BaseModel):
    """Return a verified extractive answer or evidence abstention."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    question: str
    answer: str | None
    abstained: bool
    abstention_reason: AbstentionReason | None
    claims: tuple[GroundedClaim, ...]
    citations: tuple[GroundedCitation, ...]
    evidence_count: int = Field(ge=0)
    sufficiency: EvidenceSufficiency
    termination_reason: TerminationReason
    retrieval_mode: Literal[SearchMode.RERANK] = SearchMode.RERANK
    reranker_model: str | None
    latency_ms: float = Field(ge=0)


class AgentAnswerRequest(BaseModel):
    """Validate one bounded Agentic RAG request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    max_claims: int = Field(default=1, ge=1, le=3)
    max_retrieval_attempts: int = Field(default=2, ge=1, le=3)
    max_steps: int = Field(default=14, ge=1, le=20)
    tool_timeout_seconds: float = Field(default=45.0, gt=0, le=60)
    max_repair_attempts: int = Field(default=1, ge=0, le=1)


async def get_live_health() -> LiveHealthResponse:
    """Return the API process liveness state.

    Returns
    -------
    LiveHealthResponse
        A response indicating that the process can serve requests.
    """
    return LiveHealthResponse()


async def get_document_pdf(document_id: str) -> FileResponse:
    """Return the configured source PDF for page-level Citation links.

    Parameters
    ----------
    document_id : str
        Stable identifier of the requested document.

    Returns
    -------
    fastapi.responses.FileResponse
        Inline PDF response rendered by the browser.

    Raises
    ------
    fastapi.HTTPException
        If the identifier is unknown or the configured PDF does not exist.
    """
    if document_id != DEFAULT_DOCUMENT_ID:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    pdf_path = Path(os.getenv("DOCUMENT_PDF_PATH", str(DEFAULT_PDF_PATH)))
    if not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document PDF is unavailable",
        )
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )


@lru_cache(maxsize=1)
def get_search_service() -> LocalSearchService:
    """Build and cache the local PDF search service.

    Returns
    -------
    LocalSearchService
        Sparse index and lazy dense index over the configured PDF.

    Raises
    ------
    fastapi.HTTPException
        If the configured local PDF cannot be extracted.
    """
    pdf_path = Path(os.getenv("DOCUMENT_PDF_PATH", str(DEFAULT_PDF_PATH)))
    try:
        pages = extract_pdf(pdf_path, DEFAULT_VERSION_ID)
    except PdfExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Local search PDF is unavailable: {pdf_path}",
        ) from exc
    searchable_pages = tuple(
        page
        for page in pages
        if page.page.page_number not in DEFAULT_EXCLUDED_CORPUS_PAGES
    )
    chunks = build_page_chunks(searchable_pages, DEFAULT_VERSION_ID)
    reranker_model = os.getenv("RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    return LocalSearchService(
        chunks,
        FastEmbedder(),
        FastEmbedReranker(model_name=reranker_model),
    )


def get_retrieval_agent(
    search_service: Annotated[LocalSearchService, Depends(get_search_service)],
) -> RetrievalAgent:
    """Build one Agent graph around cached in-process application tools.

    Parameters
    ----------
    search_service : LocalSearchService
        Cached local retrieval service supplied by FastAPI.

    Returns
    -------
    RetrievalAgent
        Bounded LangGraph agent using local typed tools without MCP transport.
    """
    tools = LocalRetrievalAgentTools(
        search_service,
        document_id=DEFAULT_DOCUMENT_ID,
        document_title=DEFAULT_DOCUMENT_TITLE,
    )
    return RetrievalAgent(tools)


async def search_documents(
    request: SearchRequest,
    search_service: Annotated[LocalSearchService, Depends(get_search_service)],
) -> SearchResponse:
    """Search the configured local PDF and return page-aware chunks.

    Parameters
    ----------
    request : SearchRequest
        Validated query, retrieval mode, and result limit.
    search_service : LocalSearchService
        Cached local retrieval service supplied by FastAPI.

    Returns
    -------
    SearchResponse
        Ranked chunks with source pages and retrieval scores.
    """
    started_at = perf_counter()
    hits = search_service.search(request.query, request.mode, request.top_k)
    latency_ms = (perf_counter() - started_at) * 1_000
    embedding_model = (
        None if request.mode is SearchMode.BM25 else search_service.embedding_model_name
    )
    if request.mode is SearchMode.RERANK:
        embedding_model = None
    return SearchResponse(
        query_id=uuid4(),
        document_id=DEFAULT_DOCUMENT_ID,
        mode=request.mode,
        embedding_model=embedding_model,
        reranker_model=(
            search_service.reranker_model_name
            if request.mode is SearchMode.RERANK
            else None
        ),
        results=[
            SearchResultResponse(
                rank=rank,
                chunk_id=hit.chunk.chunk_id,
                version_id=hit.chunk.version_id,
                page_start=hit.chunk.page_start,
                page_end=hit.chunk.page_end,
                text=hit.chunk.text,
                score=hit.score,
            )
            for rank, hit in enumerate(hits, start=1)
        ],
        latency_ms=latency_ms,
    )


async def answer_question(
    request: AnswerRequest,
    search_service: Annotated[LocalSearchService, Depends(get_search_service)],
) -> AnswerResponse:
    """Answer from reranked PDF evidence and verify every source quote.

    Parameters
    ----------
    request : AnswerRequest
        Validated question and evidence limit.
    search_service : LocalSearchService
        Cached local retrieval and reranking service.

    Returns
    -------
    AnswerResponse
        Extractive answer with page citations, or a normal abstention response.
    """
    started_at = perf_counter()
    hits = search_service.search(request.question, SearchMode.RERANK, request.top_k)
    evidence_pack = build_evidence_pack(
        request.question,
        hits,
        document_id=DEFAULT_DOCUMENT_ID,
        document_title=DEFAULT_DOCUMENT_TITLE,
        max_evidence=request.top_k,
    )
    grounded_answer = build_grounded_answer(
        evidence_pack,
        max_claims=request.max_claims,
    )
    latency_ms = (perf_counter() - started_at) * 1_000
    return AnswerResponse(
        request_id=uuid4(),
        question=request.question,
        answer=grounded_answer.answer,
        abstained=grounded_answer.abstained,
        abstention_reason=grounded_answer.abstention_reason,
        claims=grounded_answer.claims,
        citations=grounded_answer.citations,
        evidence_count=grounded_answer.evidence_count,
        sufficiency=grounded_answer.sufficiency,
        termination_reason=grounded_answer.termination_reason,
        reranker_model=search_service.reranker_model_name,
        latency_ms=latency_ms,
    )


async def answer_with_agent(
    request: AgentAnswerRequest,
    agent: Annotated[RetrievalAgent, Depends(get_retrieval_agent)],
) -> AgentRun:
    """Run bounded search, rewrite, rerank, validation, and abstention.

    Parameters
    ----------
    request : AgentAnswerRequest
        Validated question and hard execution limits.
    agent : RetrievalAgent
        Dependency-injected LangGraph retrieval agent.

    Returns
    -------
    AgentRun
        Grounded answer and reconstructable tool trajectory.
    """
    return agent.run(
        request.question,
        top_k=request.top_k,
        max_claims=request.max_claims,
        max_retrieval_attempts=request.max_retrieval_attempts,
        max_steps=request.max_steps,
        tool_timeout_seconds=request.tool_timeout_seconds,
        max_repair_attempts=request.max_repair_attempts,
    )


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns
    -------
    FastAPI
        Configured HTTP application.
    """
    application = FastAPI(
        title="Semiconductor Document RAG API",
        version="0.1.0",
    )
    application.add_api_route(
        "/health/live",
        get_live_health,
        methods=["GET"],
        response_model=LiveHealthResponse,
        tags=["health"],
    )
    application.add_api_route(
        "/v1/search",
        search_documents,
        methods=["POST"],
        response_model=SearchResponse,
        tags=["search"],
    )
    application.add_api_route(
        "/v1/documents/{document_id}/pdf",
        get_document_pdf,
        methods=["GET"],
        response_class=FileResponse,
        tags=["documents"],
    )
    application.add_api_route(
        "/v1/answers",
        answer_question,
        methods=["POST"],
        response_model=AnswerResponse,
        tags=["answers"],
    )
    application.add_api_route(
        "/v1/agent/answers",
        answer_with_agent,
        methods=["POST"],
        response_model=AgentRun,
        tags=["agent"],
    )
    return application


app = create_app()
