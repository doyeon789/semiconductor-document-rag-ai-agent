"""Create the HTTP API application and local document search contract."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.ingestion import (
    PdfExtractionError,
    build_page_chunks,
    extract_pdf,
)
from semiconductor_rag.retrieval import FastEmbedder, LocalSearchService, SearchMode

DEFAULT_DOCUMENT_ID = "SEMI-8P-RAG-KO"
DEFAULT_DOCUMENT_VERSION = "1.3"
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
    results: list[SearchResultResponse]
    latency_ms: float = Field(ge=0)


async def get_live_health() -> LiveHealthResponse:
    """Return the API process liveness state.

    Returns
    -------
    LiveHealthResponse
        A response indicating that the process can serve requests.
    """
    return LiveHealthResponse()


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
    return LocalSearchService(chunks, FastEmbedder())


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
    return SearchResponse(
        query_id=uuid4(),
        document_id=DEFAULT_DOCUMENT_ID,
        mode=request.mode,
        embedding_model=embedding_model,
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
    return application


app = create_app()
