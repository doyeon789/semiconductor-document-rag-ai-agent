"""Unit tests for deterministic cross-encoder candidate reranking."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

import pytest

from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import (
    DEFAULT_RERANKER_MODEL,
    FastEmbedReranker,
    SearchHit,
    rerank_search_hits,
)

VERSION_ID = UUID("77777777-7777-4777-8777-777777777777")


class TestReranker:
    """Score candidates from explicit marker terms."""

    model_name = "test-reranker"

    def prepare(self) -> None:
        """Provide a no-op preparation hook for the test adapter."""

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        """Return a higher score for the marked relevant document.

        Parameters
        ----------
        query : str
            Ignored test query.
        documents : collections.abc.Sequence[str]
            Candidate texts to score.

        Returns
        -------
        tuple[float, ...]
            Stable relevance scores.
        """
        return tuple(0.9 if "relevant" in document else 0.1 for document in documents)


def _make_hit(number: int, text: str, score: float) -> SearchHit:
    """Create a stable page-aware candidate hit.

    Parameters
    ----------
    number : int
        Stable identifier and page number.
    text : str
        Candidate text.
    score : float
        First-stage retrieval score.

    Returns
    -------
    SearchHit
        Valid test candidate.
    """
    return SearchHit(
        chunk=Chunk(
            chunk_id=UUID(int=number),
            version_id=VERSION_ID,
            chunk_type=ChunkType.TEXT,
            text=text,
            page_start=number,
            page_end=number,
            token_count=len(text.split()),
            content_hash=sha256(text.encode()).hexdigest(),
        ),
        score=score,
    )


def test_reranker_promotes_semantically_relevant_candidate() -> None:
    """Replace first-stage order with cross-encoder relevance order."""
    hits = (
        _make_hit(1, "lexical candidate", 10.0),
        _make_hit(2, "relevant process explanation", 1.0),
    )

    reranked = rerank_search_hits("process question", hits, TestReranker())

    assert [hit.chunk.page_start for hit in reranked] == [2, 1]
    assert [hit.score for hit in reranked] == [0.9, 0.1]


def test_reranker_rejects_nonpositive_limit() -> None:
    """Reject invalid result limits before model inference."""
    with pytest.raises(ValueError, match="top_k must be positive"):
        rerank_search_hits("query", (), TestReranker(), top_k=0)


def test_fastembed_reranker_exposes_version_without_loading_model() -> None:
    """Record the configured multilingual model before expensive inference."""
    reranker = FastEmbedReranker()

    assert reranker.model_name == DEFAULT_RERANKER_MODEL
