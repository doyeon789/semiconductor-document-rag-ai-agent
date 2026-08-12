"""Rerank retrieved chunks with a lazy multilingual cross-encoder."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from semiconductor_rag.retrieval.models import SearchHit

DEFAULT_RERANKER_MODEL = "jinaai/jina-reranker-v2-base-multilingual"


class Reranker(Protocol):
    """Define the behavior required to score query and document pairs."""

    model_name: str

    def prepare(self) -> None:
        """Load model resources before measured inference."""
        ...

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        """Score documents against one query in their original order.

        Parameters
        ----------
        query : str
            User search query.
        documents : collections.abc.Sequence[str]
            Candidate document texts.

        Returns
        -------
        tuple[float, ...]
            One relevance score per candidate document.
        """
        ...


class FastEmbedReranker:
    """Score candidates with a local multilingual cross-encoder.

    Parameters
    ----------
    model_name : str, default=DEFAULT_RERANKER_MODEL
        FastEmbed-supported cross-encoder model identifier.
    cache_dir : str or pathlib.Path, default="indexes/models"
        Ignored local directory used to cache model files.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        cache_dir: str | Path = "indexes/models",
    ) -> None:
        """Configure a lazy-loading cross-encoder."""
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        self.model_name = model_name
        self._cache_dir = str(cache_dir)
        self._model: TextCrossEncoder | None = None

    def prepare(self) -> None:
        """Load model resources before measured inference."""
        self._get_model()

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        """Score documents against one non-empty query.

        Parameters
        ----------
        query : str
            User search query.
        documents : collections.abc.Sequence[str]
            Candidate document texts.

        Returns
        -------
        tuple[float, ...]
            One relevance score per candidate document.

        Raises
        ------
        ValueError
            If the query or a candidate document is blank, or if the model
            returns an unexpected number of scores.
        """
        if not query.strip():
            raise ValueError("query must not be blank")
        if any(not document.strip() for document in documents):
            raise ValueError("candidate documents must not be blank")
        if not documents:
            return ()
        scores = tuple(
            float(score) for score in self._get_model().rerank(query, documents)
        )
        if len(scores) != len(documents):
            raise ValueError("reranker must return one score per candidate document")
        return scores

    def _get_model(self) -> TextCrossEncoder:
        """Create the cross-encoder wrapper once and reuse it.

        Returns
        -------
        fastembed.rerank.cross_encoder.TextCrossEncoder
            Cached FastEmbed cross-encoder wrapper.
        """
        if self._model is None:
            self._model = TextCrossEncoder(
                model_name=self.model_name,
                cache_dir=self._cache_dir,
                lazy_load=True,
            )
        return self._model


def rerank_search_hits(
    query: str,
    hits: Sequence[SearchHit],
    reranker: Reranker,
    top_k: int = 5,
) -> tuple[SearchHit, ...]:
    """Replace retrieval scores with cross-encoder relevance and rerank hits.

    Parameters
    ----------
    query : str
        User search query.
    hits : collections.abc.Sequence[SearchHit]
        Candidate hits ordered by the first-stage retriever.
    reranker : Reranker
        Query-document scoring adapter.
    top_k : int, default=5
        Maximum number of reranked hits to return.

    Returns
    -------
    tuple[SearchHit, ...]
        Candidates ordered by descending cross-encoder score and stable ID.

    Raises
    ------
    ValueError
        If ``top_k`` is not positive or the reranker score count is invalid.
    """
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not hits:
        return ()
    scores = reranker.score(query, [hit.chunk.text for hit in hits])
    if len(scores) != len(hits):
        raise ValueError("reranker must return one score per search hit")
    reranked = (
        SearchHit(chunk=hit.chunk, score=score)
        for hit, score in zip(hits, scores, strict=True)
    )
    return tuple(
        sorted(
            reranked,
            key=lambda hit: (-hit.score, str(hit.chunk.chunk_id)),
        )[:top_k]
    )
