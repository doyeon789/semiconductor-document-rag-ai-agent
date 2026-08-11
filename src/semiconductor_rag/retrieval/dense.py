"""In-memory cosine similarity search over dense chunk embeddings."""

from __future__ import annotations

import math
from collections.abc import Sequence

from semiconductor_rag.domain import Chunk
from semiconductor_rag.retrieval.embedding import Embedder, EmbeddingVector
from semiconductor_rag.retrieval.models import SearchHit


class DenseIndex:
    """Rank an immutable collection of chunks by cosine similarity.

    Parameters
    ----------
    chunks : collections.abc.Sequence[Chunk]
        Chunks to embed and keep in memory.
    embedder : Embedder
        Model adapter used for documents and queries.
    """

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        """Embed and normalize all source chunks once when building the index."""
        self._chunks = tuple(chunks)
        self._embedder = embedder
        vectors = (
            embedder.embed_documents([chunk.text for chunk in self._chunks])
            if self._chunks
            else ()
        )
        if len(vectors) != len(self._chunks):
            raise ValueError("embedder must return one vector per chunk")
        self._vectors = tuple(_normalize_vector(vector) for vector in vectors)
        dimensions = {len(vector) for vector in self._vectors}
        if len(dimensions) > 1:
            raise ValueError("document embeddings must share one dimension")

    @property
    def model_name(self) -> str:
        """Return the embedding model identifier.

        Returns
        -------
        str
            Configured embedding model name.
        """
        return self._embedder.model_name

    def search(self, query: str, top_k: int = 5) -> tuple[SearchHit, ...]:
        """Return chunks with the highest cosine similarity to a query.

        Parameters
        ----------
        query : str
            User search query.
        top_k : int, default=5
            Maximum number of results to return.

        Returns
        -------
        tuple[SearchHit, ...]
            Hits ordered by descending cosine similarity and stable chunk ID.

        Raises
        ------
        ValueError
            If the query is blank, ``top_k`` is invalid, or vector dimensions
            do not match.
        """
        if not query.strip():
            raise ValueError("query must not be blank")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if not self._chunks:
            return ()

        query_vector = _normalize_vector(self._embedder.embed_query(query))
        if len(query_vector) != len(self._vectors[0]):
            raise ValueError("query and document embedding dimensions must match")
        hits = (
            SearchHit(
                chunk=chunk,
                score=sum(
                    query_value * document_value
                    for query_value, document_value in zip(
                        query_vector,
                        document_vector,
                        strict=True,
                    )
                ),
            )
            for chunk, document_vector in zip(
                self._chunks,
                self._vectors,
                strict=True,
            )
        )
        ranked_hits = sorted(
            hits,
            key=lambda hit: (-hit.score, str(hit.chunk.chunk_id)),
        )
        return tuple(ranked_hits[:top_k])


def _normalize_vector(vector: EmbeddingVector) -> EmbeddingVector:
    """Scale a non-zero dense vector to unit length.

    Parameters
    ----------
    vector : EmbeddingVector
        Dense embedding values.

    Returns
    -------
    EmbeddingVector
        Unit-length dense vector.

    Raises
    ------
    ValueError
        If the vector is empty or has zero magnitude.
    """
    if not vector:
        raise ValueError("embedding vectors must not be empty")
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise ValueError("embedding vectors must not have zero magnitude")
    return tuple(value / magnitude for value in vector)
