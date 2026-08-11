"""Unit tests for the deterministic in-memory BM25 index."""

from hashlib import sha256
from uuid import UUID

import pytest

from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import BM25Index, tokenize_search_text

VERSION_ID = UUID("55555555-5555-4555-8555-555555555555")


def _make_chunk(number: int, page: int, text: str) -> Chunk:
    """Create a stable searchable chunk for retrieval tests.

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


def test_tokenize_search_text_preserves_codes_and_korean_fragments() -> None:
    """Keep equipment-like codes while adding Korean character tokens."""
    tokens = tokenize_search_text("P03-LITH-02 식각률은")

    assert "p03-lith-02" in tokens
    assert "식각률은" in tokens
    assert "식각" in tokens


def test_bm25_ranks_exact_semiconductor_terms_first() -> None:
    """Prefer a chunk containing the exact process terms in the query."""
    index = BM25Index(
        [
            _make_chunk(1, 8, "건식 산화는 치밀한 막에 유리하다."),
            _make_chunk(2, 16, "건식 식각은 플라즈마를 이용한다."),
            _make_chunk(3, 31, "패키지 휨은 접속 신뢰성에 영향을 준다."),
        ]
    )

    hits = index.search("건식 산화의 특징은?", top_k=2)

    assert hits[0].chunk.page_start == 8
    assert hits[0].score > hits[1].score


def test_bm25_uses_chunk_id_for_deterministic_ties() -> None:
    """Return tied chunks in stable identifier order."""
    index = BM25Index(
        [
            _make_chunk(2, 2, "동일 검색어"),
            _make_chunk(1, 1, "동일 검색어"),
        ]
    )

    hits = index.search("동일 검색어")

    assert [hit.chunk.chunk_id.int for hit in hits] == [1, 2]


def test_bm25_rejects_blank_queries_and_invalid_limits() -> None:
    """Reject requests that cannot produce a meaningful ranked result."""
    index = BM25Index([_make_chunk(1, 1, "산화 공정")])

    with pytest.raises(ValueError, match="query"):
        index.search("   ")
    with pytest.raises(ValueError, match="top_k"):
        index.search("산화", top_k=0)
