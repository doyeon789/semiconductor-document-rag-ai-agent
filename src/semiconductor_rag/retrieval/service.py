"""Local retrieval service that selects sparse, dense, or hybrid search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from uuid import UUID

from semiconductor_rag.domain import Chunk, DocumentSource
from semiconductor_rag.retrieval.bm25 import BM25Index
from semiconductor_rag.retrieval.dense import DenseIndex
from semiconductor_rag.retrieval.embedding import Embedder
from semiconductor_rag.retrieval.hybrid import HybridIndex
from semiconductor_rag.retrieval.models import SearchHit
from semiconductor_rag.retrieval.reranking import Reranker, rerank_search_hits


class SearchMode(StrEnum):
    """Select one supported local retrieval strategy."""

    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"
    RERANK = "rerank"


class LocalSearchService:
    """Search one immutable local chunk corpus with selectable strategies.

    Parameters
    ----------
    chunks : collections.abc.Sequence[Chunk]
        Page-traceable chunks to search.
    embedder : Embedder
        Dense model adapter. Its document index is created only when needed.
    sources_by_version : mapping of uuid.UUID to DocumentSource or None
        Optional document metadata used to enrich every returned hit.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        embedder: Embedder,
        reranker: Reranker | None = None,
        rerank_candidate_k: int = 10,
        sources_by_version: Mapping[UUID, DocumentSource] | None = None,
    ) -> None:
        """Build the lightweight sparse index and retain dense configuration."""
        if rerank_candidate_k < 1:
            raise ValueError("rerank_candidate_k must be positive")
        self._chunks = tuple(chunks)
        self._embedder = embedder
        self._reranker = reranker
        self._rerank_candidate_k = rerank_candidate_k
        self._sources_by_version = dict(sources_by_version or {})
        missing_versions = {chunk.version_id for chunk in self._chunks}.difference(
            self._sources_by_version
        )
        if self._sources_by_version and missing_versions:
            raise ValueError("every chunk version requires document source metadata")
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

    @property
    def reranker_model_name(self) -> str | None:
        """Return the configured reranker model identifier when available.

        Returns
        -------
        str or None
            Reranker model name, or ``None`` when reranking is not configured.
        """
        return None if self._reranker is None else self._reranker.model_name

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.BM25,
        top_k: int = 5,
    ) -> tuple[SearchHit, ...]:
        """Search the local corpus with the selected retrieval strategy.

        Parameters
        ----------
        query : str
            User search query.
        mode : SearchMode, default=SearchMode.BM25
            Sparse, dense, or fused retrieval strategy.
        top_k : int, default=5
            Maximum number of results.

        Returns
        -------
        tuple[SearchHit, ...]
            Ranked page-traceable chunks.
        """
        if mode is SearchMode.BM25:
            hits = self._bm25_index.search(query, top_k)
        elif mode is SearchMode.RERANK:
            if self._reranker is None:
                raise ValueError("rerank mode requires a configured reranker")
            candidates = HybridIndex(
                self._bm25_index,
                self._get_dense_index(),
            ).search(
                query,
                max(top_k, self._rerank_candidate_k),
            )
            hits = rerank_search_hits(query, candidates, self._reranker, top_k)
        else:
            dense_index = self._get_dense_index()
            if mode is SearchMode.DENSE:
                hits = dense_index.search(query, top_k)
            else:
                hits = HybridIndex(self._bm25_index, dense_index).search(query, top_k)
        return self._attach_sources(hits)

    def prepare(self, mode: SearchMode) -> None:
        """Prepare one retrieval strategy before latency measurement.

        Parameters
        ----------
        mode : SearchMode
            Retrieval strategy that will be used next.
        """
        if mode is SearchMode.RERANK:
            if self._reranker is None:
                raise ValueError("rerank mode requires a configured reranker")
            self._get_dense_index()
            self._reranker.prepare()
        elif mode is not SearchMode.BM25:
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

    def _attach_sources(
        self,
        hits: tuple[SearchHit, ...],
    ) -> tuple[SearchHit, ...]:
        """Attach public document metadata after ranking is complete.

        Parameters
        ----------
        hits : tuple of SearchHit
            Ranked hits produced by one local index strategy.

        Returns
        -------
        tuple of SearchHit
            Hits enriched from their chunk version identifiers.
        """
        if not self._sources_by_version:
            return hits
        return tuple(
            SearchHit(
                chunk=hit.chunk,
                score=hit.score,
                source=self._sources_by_version[hit.chunk.version_id],
            )
            for hit in hits
        )
