"""Local retrieval service that selects sparse, dense, or hybrid search."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from semiconductor_rag.domain import Chunk
from semiconductor_rag.retrieval.bm25 import BM25Index
from semiconductor_rag.retrieval.dense import DenseIndex
from semiconductor_rag.retrieval.embedding import Embedder
from semiconductor_rag.retrieval.hybrid import HybridIndex
from semiconductor_rag.retrieval.models import SearchHit


class SearchMode(StrEnum):
    """Select one supported local retrieval strategy."""

    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"


class LocalSearchService:
    """Search one immutable local chunk corpus with selectable strategies.

    Parameters
    ----------
    chunks : collections.abc.Sequence[Chunk]
        Page-traceable chunks to search.
    embedder : Embedder
        Dense model adapter. Its document index is created only when needed.
    """

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        """Build the lightweight sparse index and retain dense configuration."""
        self._chunks = tuple(chunks)
        self._embedder = embedder
        self._bm25_index = BM25Index(self._chunks)
        self._dense_index: DenseIndex | None = None

    @property
    def embedding_model_name(self) -> str:
        """Return the configured dense embedding model identifier.

        Returns
        -------
        str
            Embedding model name without forcing model inference.
        """
        return self._embedder.model_name

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.HYBRID,
        top_k: int = 5,
    ) -> tuple[SearchHit, ...]:
        """Search the local corpus with the selected retrieval strategy.

        Parameters
        ----------
        query : str
            User search query.
        mode : SearchMode, default=SearchMode.HYBRID
            Sparse, dense, or fused retrieval strategy.
        top_k : int, default=5
            Maximum number of results.

        Returns
        -------
        tuple[SearchHit, ...]
            Ranked page-traceable chunks.
        """
        if mode is SearchMode.BM25:
            return self._bm25_index.search(query, top_k)
        dense_index = self._get_dense_index()
        if mode is SearchMode.DENSE:
            return dense_index.search(query, top_k)
        return HybridIndex(self._bm25_index, dense_index).search(query, top_k)

    def prepare(self, mode: SearchMode) -> None:
        """Prepare one retrieval strategy before latency measurement.

        Parameters
        ----------
        mode : SearchMode
            Retrieval strategy that will be used next.
        """
        if mode is not SearchMode.BM25:
            self._get_dense_index()

    def _get_dense_index(self) -> DenseIndex:
        """Build the dense index on first use and reuse it afterward.

        Returns
        -------
        DenseIndex
            Cached in-memory dense index.
        """
        if self._dense_index is None:
            self._dense_index = DenseIndex(self._chunks, self._embedder)
        return self._dense_index
