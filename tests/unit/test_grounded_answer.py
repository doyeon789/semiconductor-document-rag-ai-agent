"""Unit tests for extractive grounded answers and citation verification."""

from hashlib import sha256
from uuid import UUID

from semiconductor_rag.answering import (
    EvidenceSufficiency,
    TerminationReason,
    build_evidence_pack,
    build_grounded_answer,
    validate_citation,
)
from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import SearchHit

VERSION_ID = UUID("55555555-5555-4555-8555-555555555555")


def _make_hit(text: str) -> SearchHit:
    """Create one page-grounded answer test hit.

    Parameters
    ----------
    text : str
        Source text used by the answer.

    Returns
    -------
    SearchHit
        Valid page-aware retrieval result.
    """
    return SearchHit(
        chunk=Chunk(
            chunk_id=UUID(int=1),
            version_id=VERSION_ID,
            chunk_type=ChunkType.TEXT,
            text=text,
            page_start=8,
            page_end=8,
            token_count=len(text.split()),
            content_hash=sha256(text.encode()).hexdigest(),
        ),
        score=0.9,
    )


def test_grounded_answer_quotes_the_matching_source_sentence() -> None:
    """Use an exact relevant sentence and retain its PDF page citation."""
    source = "산화 공정 개요. 습식 산화는 빠른 성장 속도에 적합하다."
    pack = build_evidence_pack(
        "습식 산화의 특징은?",
        (_make_hit(source),),
        "doc-1",
        "공정 안내서",
    )

    result = build_grounded_answer(pack)

    assert result.abstained is False
    assert result.sufficiency is EvidenceSufficiency.SUFFICIENT
    assert result.termination_reason is TerminationReason.ANSWER_VALIDATED
    assert result.claims[0].text == "습식 산화는 빠른 성장 속도에 적합하다."
    assert result.citations[0].quote in source
    assert result.citations[0].page_number == 8
    assert "공정 안내서, p.8" in (result.answer or "")


def test_grounded_answer_abstains_without_evidence() -> None:
    """Return a normal structured abstention instead of inventing an answer."""
    pack = build_evidence_pack("문서에 없는 질문", (), "doc-1", "공정 안내서")

    result = build_grounded_answer(pack)

    assert result.abstained is True
    assert result.answer is None
    assert result.claims == ()
    assert result.citations == ()
    assert result.sufficiency is EvidenceSufficiency.INSUFFICIENT


def test_citation_validator_rejects_quote_mismatch() -> None:
    """Reject a citation quote that cannot be found in the source block."""
    pack = build_evidence_pack(
        "습식 산화",
        (_make_hit("습식 산화는 빠르다."),),
        "doc-1",
        "공정 안내서",
    )
    result = build_grounded_answer(pack)
    mismatched = result.citations[0].model_copy(update={"quote": "원문에 없는 주장"})

    assert validate_citation(mismatched, pack.blocks[0]) is False
