"""Reciprocal-rank fusion for local sparse and dense search results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from semiconductor_rag.domain import Chunk
from semiconductor_rag.retrieval.models import SearchHit


class SearchIndex(Protocol):
    """Define the search behavior required by the hybrid index."""

    def search(self, query: str, top_k: int = 5) -> tuple[SearchHit, ...]:
        """Return ranked chunks for a query.

        Parameters
        ----------
        query : str
            User search query.
        top_k : int, default=5
            Maximum number of results.

        Returns
        -------
        tuple[SearchHit, ...]
            Ranked search hits.
        """
        ...


def reciprocal_rank_fusion(
    result_sets: Sequence[Sequence[SearchHit]],
    top_k: int = 5,
    rank_constant: int = 60,
    weights: Sequence[float] | None = None,
) -> tuple[SearchHit, ...]:
    """Fuse ranked result sets without comparing their raw score scales.

    Parameters
    ----------
    result_sets : collections.abc.Sequence[collections.abc.Sequence[SearchHit]]
        Independently ranked result lists.
    top_k : int, default=5
        Maximum number of fused results.
    rank_constant : int, default=60
        Positive RRF rank offset that controls how quickly rank weight decays.
    weights : collections.abc.Sequence[float] or None, default=None
        Non-negative weight for each result set. Equal weights are used when
        omitted.

    Returns
    -------
    tuple[SearchHit, ...]
        Deduplicated chunks ranked by summed reciprocal rank.

    Raises
    ------
    ValueError
        If limits or result-set weights are invalid.
    """
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    fusion_weights = (
        tuple(weights) if weights is not None else (1.0,) * len(result_sets)
    )
    if len(fusion_weights) != len(result_sets):
        raise ValueError("weights must match the number of result sets")
    if any(weight < 0 for weight in fusion_weights) or not any(fusion_weights):
        raise ValueError(
            "weights must be non-negative with at least one positive value"
        )

    fused_scores: defaultdict[UUID, float] = defaultdict(float)
    chunks_by_id: dict[UUID, Chunk] = {}
    for hits, weight in zip(result_sets, fusion_weights, strict=True):
        seen_chunk_ids: set[UUID] = set()
        for rank, hit in enumerate(hits, start=1):
            chunk_id = hit.chunk.chunk_id
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            chunks_by_id.setdefault(chunk_id, hit.chunk)
            fused_scores[chunk_id] += weight / (rank_constant + rank)

    fused_hits = (
        SearchHit(chunk=chunks_by_id[chunk_id], score=score)
        for chunk_id, score in fused_scores.items()
    )
    ranked_hits = sorted(
        fused_hits,
        key=lambda hit: (-hit.score, str(hit.chunk.chunk_id)),
    )
    return tuple(ranked_hits[:top_k])


class HybridIndex:
    """Combine sparse and dense retrieval through reciprocal-rank fusion.

    Parameters
    ----------
    sparse_index : SearchIndex
        Exact-term-oriented retrieval index.
    dense_index : SearchIndex
        Embedding-oriented retrieval index.
    candidate_k : int, default=20
        Candidate count requested from each child index before fusion.
    rank_constant : int, default=60
        Positive RRF rank offset.
    sparse_weight : float, default=0.75
        Relative contribution of exact-term rankings.
    dense_weight : float, default=0.25
        Relative contribution of semantic rankings.
    """

    def __init__(
        self,
        sparse_index: SearchIndex,
        dense_index: SearchIndex,
        candidate_k: int = 20,
        rank_constant: int = 60,
        sparse_weight: float = 0.75,
        dense_weight: float = 0.25,
    ) -> None:
        """Store child indexes and validate fusion parameters."""
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        if rank_constant < 1:
            raise ValueError("rank_constant must be positive")
        if sparse_weight < 0 or dense_weight < 0:
            raise ValueError("fusion weights must be non-negative")
        if sparse_weight + dense_weight == 0:
            raise ValueError("at least one fusion weight must be positive")
        self._sparse_index = sparse_index
        self._dense_index = dense_index
        self._candidate_k = candidate_k
        self._rank_constant = rank_constant
        self._weights = (sparse_weight, dense_weight)

    def search(self, query: str, top_k: int = 5) -> tuple[SearchHit, ...]:
        """Search both child indexes and fuse their rankings.

        Parameters
        ----------
        query : str
            User search query.
        top_k : int, default=5
            Maximum number of fused results.

        Returns
        -------
        tuple[SearchHit, ...]
            Fused hits with deterministic tie ordering.

        Raises
        ------
        ValueError
            If the query is blank or ``top_k`` is not positive.
        """
        if not query.strip():
            raise ValueError("query must not be blank")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        candidate_k = max(self._candidate_k, top_k)
        sparse_hits = self._sparse_index.search(query, candidate_k)
        dense_hits = self._dense_index.search(query, candidate_k)
        return reciprocal_rank_fusion(
            (sparse_hits, dense_hits),
            top_k=top_k,
            rank_constant=self._rank_constant,
            weights=self._weights,
        )
