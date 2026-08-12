"""Unit tests for local dense cosine search."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

import pytest

from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import DenseIndex, EmbeddingVector

VERSION_ID = UUID("66666666-6666-4666-8666-666666666666")


class KeywordEmbedder:
    """Map test keywords into a deterministic two-dimensional space."""

    model_name = "keyword-test-embedding"

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        """Embed each test document.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Source texts.

        Returns
        -------
        tuple[EmbeddingVector, ...]
            Deterministic vectors for the source texts.
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
            Deterministic vector for the query.
        """
        return self._embed(query)

    def _embed(self, text: str) -> EmbeddingVector:
        """Convert process keywords into orthogonal features.

        Parameters
        ----------
        text : str
            Test text.

        Returns
        -------
        EmbeddingVector
            Two-dimensional keyword vector.
        """
        return (
            float("산화" in text or "절연막" in text),
            float("패키지" in text or "조립" in text),
        )


def _make_chunk(number: int, page: int, text: str) -> Chunk:
    """Create a stable searchable chunk for dense retrieval tests.

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


def test_dense_search_finds_semantically_mapped_document() -> None:
    """Find an oxidation document from its insulating-film description."""
    index = DenseIndex(
        [
            _make_chunk(1, 8, "산화 공정은 실리콘 표면을 변화시킨다."),
            _make_chunk(2, 31, "패키지 공정은 다이를 조립한다."),
        ],
        KeywordEmbedder(),
    )

    hits = index.search("절연막은 왜 필요한가?", top_k=1)

    assert hits[0].chunk.page_start == 8
    assert hits[0].score == pytest.approx(1.0)
    assert index.model_name == "keyword-test-embedding"


def test_dense_search_uses_chunk_id_for_deterministic_ties() -> None:
    """Return equally similar chunks in stable identifier order."""
    index = DenseIndex(
        [
            _make_chunk(2, 2, "산화 절연막"),
            _make_chunk(1, 1, "산화 절연막"),
        ],
        KeywordEmbedder(),
    )

    hits = index.search("산화")

    assert [hit.chunk.chunk_id.int for hit in hits] == [1, 2]


def test_dense_search_rejects_zero_vectors() -> None:
    """Reject documents that an embedding model cannot represent."""
    with pytest.raises(ValueError, match="zero magnitude"):
        DenseIndex([_make_chunk(1, 1, "관련 없는 문장")], KeywordEmbedder())
