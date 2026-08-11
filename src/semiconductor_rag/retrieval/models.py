"""Shared result contracts for local retrieval implementations."""

from dataclasses import dataclass

from semiconductor_rag.domain import Chunk


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Pair a source chunk with its retrieval score.

    Parameters
    ----------
    chunk : Chunk
        Page-traceable source chunk.
    score : float
        Method-specific relevance score. Larger values are more relevant.
    """

    chunk: Chunk
    score: float
