"""Unit tests for deterministic reciprocal-rank fusion."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import HybridIndex, SearchHit, reciprocal_rank_fusion

VERSION_ID = UUID("77777777-7777-4777-8777-777777777777")


def _make_chunk(number: int, page: int, text: str) -> Chunk:
    """Create a stable source chunk for fusion tests.

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


class StaticIndex:
    """Return a pre-ranked result sequence for hybrid tests."""

    def __init__(self, hits: Sequence[SearchHit]) -> None:
        """Store a fixed ranked sequence.

        Parameters
        ----------
        hits : collections.abc.Sequence[SearchHit]
            Pre-ranked test results.
        """
        self._hits = tuple(hits)

    def search(self, query: str, top_k: int = 5) -> tuple[SearchHit, ...]:
        """Return the fixed results up to the requested limit.

        Parameters
        ----------
        query : str
            Ignored non-empty test query.
        top_k : int, default=5
            Maximum number of results.

        Returns
        -------
        tuple[SearchHit, ...]
            Fixed results in their configured order.
        """
        return self._hits[:top_k]


def test_reciprocal_rank_fusion_rewards_cross_method_agreement() -> None:
    """Rank a chunk first when both retrieval methods return it highly."""
    shared = _make_chunk(1, 8, "산화막과 절연 특성")
    sparse_only = _make_chunk(2, 9, "O2 산화 조건")
    dense_only = _make_chunk(3, 10, "표면 보호막 설명")

    fused = reciprocal_rank_fusion(
        (
            [SearchHit(sparse_only, 9.0), SearchHit(shared, 5.0)],
            [SearchHit(shared, 0.9), SearchHit(dense_only, 0.8)],
        )
    )

    assert fused[0].chunk == shared
    assert {hit.chunk.chunk_id for hit in fused} == {
        shared.chunk_id,
        sparse_only.chunk_id,
        dense_only.chunk_id,
    }


def test_reciprocal_rank_fusion_is_deterministic_for_ties() -> None:
    """Resolve equal fused scores with stable chunk identifiers."""
    second = _make_chunk(2, 2, "두 번째")
    first = _make_chunk(1, 1, "첫 번째")

    fused = reciprocal_rank_fusion(([SearchHit(second, 1.0)], [SearchHit(first, 1.0)]))

    assert [hit.chunk.chunk_id.int for hit in fused] == [1, 2]


def test_hybrid_index_requests_candidates_and_limits_output() -> None:
    """Fuse child indexes and return only the requested number of hits."""
    first = _make_chunk(1, 1, "첫 번째")
    second = _make_chunk(2, 2, "두 번째")
    index = HybridIndex(
        StaticIndex([SearchHit(first, 1.0), SearchHit(second, 0.5)]),
        StaticIndex([SearchHit(second, 1.0), SearchHit(first, 0.5)]),
        candidate_k=2,
    )

    hits = index.search("결합 검색", top_k=1)

    assert len(hits) == 1
    assert hits[0].chunk == first
