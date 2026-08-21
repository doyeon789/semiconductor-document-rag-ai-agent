"""Unit tests for page-grounded evidence pack construction."""

from hashlib import sha256
from uuid import UUID

import pytest

from semiconductor_rag.answering import build_evidence_pack
from semiconductor_rag.domain import Chunk, ChunkType, DocumentSource
from semiconductor_rag.retrieval import SearchHit, SearchMode

VERSION_ID = UUID("66666666-6666-4666-8666-666666666666")


def _make_hit(
    number: int,
    page: int,
    text: str,
    score: float,
    source: DocumentSource | None = None,
) -> SearchHit:
    """Create a stable page-local search hit.

    Parameters
    ----------
    number : int
        Stable chunk identifier.
    page : int
        One-based PDF page number.
    text : str
        Evidence text.
    score : float
        Retrieval or reranker score.
    source : DocumentSource or None, default=None
        Optional public document metadata.

    Returns
    -------
    SearchHit
        Valid page-aware hit.
    """
    return SearchHit(
        chunk=Chunk(
            chunk_id=UUID(int=number),
            version_id=VERSION_ID,
            chunk_type=ChunkType.TEXT,
            text=text,
            page_start=page,
            page_end=page,
            token_count=len(text.split()),
            content_hash=sha256(text.encode()).hexdigest(),
        ),
        score=score,
        source=source,
    )


def test_evidence_pack_keeps_best_hit_per_pdf_page() -> None:
    """Deduplicate pages while preserving rank and source traceability."""
    hits = (
        _make_hit(1, 12, "공정 조건의 첫 번째 근거", 0.9),
        _make_hit(2, 12, "공정 조건과 같은 페이지의 낮은 순위 근거", 0.8),
        _make_hit(3, 15, "공정 조건의 두 번째 페이지 근거", 0.7),
    )

    pack = build_evidence_pack(
        "공정 조건은?",
        hits,
        document_id="doc-1",
        document_title="공정 안내서",
    )

    assert [block.evidence_id for block in pack.blocks] == ["E1", "E2"]
    assert [block.page_number for block in pack.blocks] == [12, 15]
    assert pack.blocks[0].chunk_id == UUID(int=1)
    assert pack.blocks[0].document_title == "공정 안내서"


def test_evidence_pack_limits_context_size() -> None:
    """Retain only the configured number of distinct evidence pages."""
    hits = tuple(
        _make_hit(number, number, f"page {number}", 1 / number)
        for number in range(1, 4)
    )

    pack = build_evidence_pack("page", hits, "doc", "title", max_evidence=2)

    assert len(pack.blocks) == 2


def test_evidence_pack_rejects_nonpositive_limit() -> None:
    """Reject an evidence budget that cannot retain any source."""
    with pytest.raises(ValueError, match="max_evidence must be positive"):
        build_evidence_pack("query", (), "doc", "title", max_evidence=0)


def test_evidence_pack_drops_candidates_without_query_overlap() -> None:
    """Exclude semantically weak candidates from answer evidence by default."""
    hits = (_make_hit(1, 8, "산화 공정 설명", 0.1),)

    pack = build_evidence_pack("초전도 큐비트", hits, "doc", "title")

    assert pack.blocks == ()


def test_evidence_pack_records_the_search_score_family() -> None:
    """Retain the retrieval mode needed to interpret confidence scores."""
    pack = build_evidence_pack(
        "산화 공정",
        (_make_hit(1, 8, "산화 공정 설명", 0.9),),
        "doc",
        "title",
        retrieval_mode=SearchMode.RERANK,
    )

    assert pack.retrieval_mode is SearchMode.RERANK


def test_evidence_pack_prefers_hit_document_metadata() -> None:
    """Use per-hit metadata instead of one legacy fallback document."""
    source = DocumentSource(
        document_id="nist-ai-rmf-1-0",
        title="NIST AI RMF 1.0",
        publisher="NIST",
        language="en-US",
        version="1.0",
    )
    hit = _make_hit(1, 12, "AI risk management framework", 0.9, source)

    pack = build_evidence_pack(
        "risk management",
        (hit,),
        document_id="legacy-document",
        document_title="Legacy Document",
    )

    assert pack.blocks[0].document_id == "nist-ai-rmf-1-0"
    assert pack.blocks[0].document_title == "NIST AI RMF 1.0"
