"""Unit tests for the local document search HTTP contract."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.main import app, get_search_service
from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import (
    EmbeddingVector,
    LocalSearchService,
)

VERSION_ID = UUID("88888888-8888-4888-8888-888888888888")


class ApiTestEmbedder:
    """Provide deterministic vectors without loading an external model."""

    model_name = "api-test-embedding"

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        """Embed all test documents.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Source texts.

        Returns
        -------
        tuple[EmbeddingVector, ...]
            Deterministic document vectors.
        """
        return tuple(self._embed(text) for text in texts)

    def embed_query(self, query: str) -> EmbeddingVector:
        """Embed one test query.

        Parameters
        ----------
        query : str
            Query text.

        Returns
        -------
        EmbeddingVector
            Deterministic query vector.
        """
        return self._embed(query)

    def _embed(self, text: str) -> EmbeddingVector:
        """Map process terms into two test dimensions.

        Parameters
        ----------
        text : str
            Source or query text.

        Returns
        -------
        EmbeddingVector
            Two-dimensional process vector.
        """
        return (
            float("산화" in text or "절연" in text),
            float("패키지" in text or "조립" in text),
        )


class ApiTestReranker:
    """Promote candidates that contain the question's answer term."""

    model_name = "api-test-reranker"

    def prepare(self) -> None:
        """Provide a no-op preparation hook for API tests."""

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        """Score oxidation evidence above unrelated candidates.

        Parameters
        ----------
        query : str
            Ignored test query.
        documents : collections.abc.Sequence[str]
            Candidate texts.

        Returns
        -------
        tuple[float, ...]
            Stable relevance scores.
        """
        return tuple(0.9 if "산화" in document else 0.1 for document in documents)


def _make_chunk(number: int, page: int, text: str) -> Chunk:
    """Create one stable API test chunk.

    Parameters
    ----------
    number : int
        Integer used to construct a stable chunk identifier.
    page : int
        One-based source page number.
    text : str
        Searchable source text.

    Returns
    -------
    Chunk
        Valid page-local chunk.
    """
    return Chunk(
        chunk_id=UUID(int=number),
        version_id=VERSION_ID,
        chunk_type=ChunkType.TEXT,
        text=text,
        page_start=page,
        page_end=page,
        token_count=len(text.split()),
        content_hash=sha256(text.encode()).hexdigest(),
    )


def _provide_test_search_service() -> LocalSearchService:
    """Return a local service used by FastAPI dependency overrides.

    Returns
    -------
    LocalSearchService
        Search service with two deterministic chunks.
    """
    return LocalSearchService(
        [
            _make_chunk(1, 8, "산화 공정은 절연막을 형성한다."),
            _make_chunk(2, 31, "패키지 공정은 다이를 조립한다."),
        ],
        ApiTestEmbedder(),
        ApiTestReranker(),
    )


def test_search_endpoint_returns_ranked_page_traceability() -> None:
    """Return rank, score, source page, and text for a search request."""
    app.dependency_overrides[get_search_service] = _provide_test_search_service
    try:
        response = TestClient(app).post(
            "/v1/search",
            json={"query": "절연막의 역할", "mode": "hybrid", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid"
    assert body["embedding_model"] == "api-test-embedding"
    assert body["reranker_model"] is None
    assert body["results"][0]["rank"] == 1
    assert body["results"][0]["page_start"] == 8
    assert body["results"][0]["page_end"] == 8
    assert "산화 공정" in body["results"][0]["text"]
    assert body["results"][0]["score"] > 0


def test_search_endpoint_uses_bm25_by_default() -> None:
    """Use the strongest measured baseline when the mode is omitted."""
    app.dependency_overrides[get_search_service] = _provide_test_search_service
    try:
        response = TestClient(app).post(
            "/v1/search",
            json={"query": "산화 공정", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "bm25"
    assert body["embedding_model"] is None
    assert body["reranker_model"] is None
    assert body["results"][0]["page_start"] == 8


def test_search_endpoint_reranks_bm25_candidates() -> None:
    """Expose reranked candidates and the cross-encoder model identifier."""
    app.dependency_overrides[get_search_service] = _provide_test_search_service
    try:
        response = TestClient(app).post(
            "/v1/search",
            json={"query": "공정", "mode": "rerank", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rerank"
    assert body["embedding_model"] is None
    assert body["reranker_model"] == "api-test-reranker"
    assert body["results"][0]["page_start"] == 8


def test_search_endpoint_rejects_unknown_modes_and_limits() -> None:
    """Reject unsupported retrieval modes and unsafe result limits."""
    app.dependency_overrides[get_search_service] = _provide_test_search_service
    try:
        client = TestClient(app)
        unknown_mode = client.post(
            "/v1/search",
            json={"query": "산화", "mode": "unknown"},
        )
        excessive_limit = client.post(
            "/v1/search",
            json={"query": "산화", "top_k": 21},
        )
    finally:
        app.dependency_overrides.clear()

    assert unknown_mode.status_code == 422
    assert excessive_limit.status_code == 422
