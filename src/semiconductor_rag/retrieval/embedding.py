"""Embedding adapter contracts and a lightweight FastEmbed implementation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

EmbeddingVector = tuple[float, ...]


class Embedder(Protocol):
    """Define the embedding behavior required by local dense retrieval."""

    model_name: str

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        """Embed source documents in their original order.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Source document texts.

        Returns
        -------
        tuple[EmbeddingVector, ...]
            One dense vector per source text.
        """
        ...

    def embed_query(self, query: str) -> EmbeddingVector:
        """Embed one search query.

        Parameters
        ----------
        query : str
            User query text.

        Returns
        -------
        EmbeddingVector
            Dense query vector.
        """
        ...


class FastEmbedder:
    """Generate multilingual embeddings with a local ONNX model.

    Parameters
    ----------
    model_name : str, default=DEFAULT_EMBEDDING_MODEL
        FastEmbed-supported model identifier.
    cache_dir : str or pathlib.Path, default="indexes/models"
        Ignored local directory used to cache model files.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: str | Path = "indexes/models",
    ) -> None:
        """Configure a lazy-loading embedding model."""
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        self.model_name = model_name
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache_dir),
            lazy_load=True,
        )

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        """Embed source documents in their original order.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Source document texts.

        Returns
        -------
        tuple[EmbeddingVector, ...]
            One dense vector per source text.
        """
        if any(not text.strip() for text in texts):
            raise ValueError("document texts must not be blank")
        return tuple(
            tuple(float(value) for value in vector)
            for vector in self._model.embed(texts)
        )

    def embed_query(self, query: str) -> EmbeddingVector:
        """Embed one non-empty search query.

        Parameters
        ----------
        query : str
            User query text.

        Returns
        -------
        EmbeddingVector
            Dense query vector.

        Raises
        ------
        ValueError
            If the query is blank or the model produces no vector.
        """
        if not query.strip():
            raise ValueError("query must not be blank")
        vectors = tuple(self._model.query_embed(query))
        if len(vectors) != 1:
            raise ValueError("embedding model must return exactly one query vector")
        return tuple(float(value) for value in vectors[0])
