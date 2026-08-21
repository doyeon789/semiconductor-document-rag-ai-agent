"""Create the HTTP API application and local document search contract."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

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
from semiconductor_rag.corpus import (
    DEFAULT_CATALOG_PATH,
    CorpusLoadError,
    LoadedCorpus,
    load_corpus,
)
from semiconductor_rag.retrieval import (
    DEFAULT_RERANKER_MODEL,
    FastEmbedder,
    FastEmbedReranker,
    LocalSearchService,
    SearchMode,
)

FALLBACK_DOCUMENT_ID = "local-document"
FALLBACK_DOCUMENT_TITLE = "Configured local document"


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
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    language: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
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
    """Return one verified corpus PDF for page-level Citation links.

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
        If the identifier is unknown or the verified PDF no longer exists.
    """
    document = get_corpus().get_document(document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if not document.pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document PDF is unavailable",
        )
    return FileResponse(
        document.pdf_path,
        media_type="application/pdf",
        filename=document.pdf_path.name,
        content_disposition_type="inline",
    )


@lru_cache(maxsize=1)
def get_corpus() -> LoadedCorpus:
    """Verify and cache the configured public document corpus.

    Returns
    -------
    LoadedCorpus
        Catalog documents, local PDF paths, and page-aware chunks.

    Raises
    ------
    fastapi.HTTPException
        If any required catalog PDF cannot be verified or extracted.
    """
    catalog_path = Path(os.getenv("CORPUS_CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    pdf_dir_value = os.getenv("CORPUS_PDF_DIR")
    pdf_dir = Path(pdf_dir_value) if pdf_dir_value else None
    try:
        return load_corpus(catalog_path=catalog_path, pdf_dir=pdf_dir)
    except (CorpusLoadError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI security corpus is unavailable or invalid",
        ) from exc


@lru_cache(maxsize=1)
def get_search_service() -> LocalSearchService:
    """Build and cache the multi-document local search service.

    Returns
    -------
    LocalSearchService
        Sparse index and lazy dense index over the verified corpus.

    Raises
    ------
    fastapi.HTTPException
        If the configured local corpus cannot be loaded.
    """
    corpus = get_corpus()
    reranker_model = os.getenv("RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    return LocalSearchService(
        corpus.chunks,
        FastEmbedder(),
        FastEmbedReranker(model_name=reranker_model),
        sources_by_version=corpus.sources_by_version,
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
        document_id=FALLBACK_DOCUMENT_ID,
        document_title=FALLBACK_DOCUMENT_TITLE,
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
    results: list[SearchResultResponse] = []
    for rank, hit in enumerate(hits, start=1):
        if hit.source is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Search result is missing document metadata",
            )
        results.append(
            SearchResultResponse(
                rank=rank,
                document_id=hit.source.document_id,
                document_title=hit.source.title,
                publisher=hit.source.publisher,
                language=hit.source.language,
                document_version=hit.source.version,
                chunk_id=hit.chunk.chunk_id,
                version_id=hit.chunk.version_id,
                page_start=hit.chunk.page_start,
                page_end=hit.chunk.page_end,
                text=hit.chunk.text,
                score=hit.score,
            )
        )
    return SearchResponse(
        query_id=uuid4(),
        mode=request.mode,
        embedding_model=embedding_model,
        reranker_model=(
            search_service.reranker_model_name
            if request.mode is SearchMode.RERANK
            else None
        ),
        results=results,
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
        document_id=FALLBACK_DOCUMENT_ID,
        document_title=FALLBACK_DOCUMENT_TITLE,
        max_evidence=request.top_k,
        retrieval_mode=SearchMode.RERANK,
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
        title="AI Security Document RAG API",
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
