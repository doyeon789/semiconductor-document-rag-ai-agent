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


def _make_hit(text: str, page: int = 8, score: float = 0.9) -> SearchHit:
    """Create one page-grounded answer test hit.

    Parameters
    ----------
    text : str
        Source text used by the answer.
    page : int, default=8
        PDF page attached to the source text.
    score : float, default=0.9
        Retrieval score attached to the source text.

    Returns
    -------
    SearchHit
        Valid page-aware retrieval result.
    """
    return SearchHit(
        chunk=Chunk(
            chunk_id=UUID(int=page),
            version_id=VERSION_ID,
            chunk_type=ChunkType.TEXT,
            text=text,
            page_start=page,
            page_end=page,
            token_count=len(text.split()),
            content_hash=sha256(text.encode()).hexdigest(),
        ),
        score=score,
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


def test_grounded_answer_prefers_page_with_more_query_concepts() -> None:
    """Avoid citing a higher-ranked page when its quote is less specific."""
    pack = build_evidence_pack(
        "건식 산화와 습식 산화의 선택 기준은?",
        (
            _make_hit("산화 공정의 일반 주의사항이다.", page=9, score=1.0),
            _make_hit(
                "건식 산화와 습식 산화는 성장 속도와 막질 기준으로 선택한다.",
                page=8,
                score=0.9,
            ),
        ),
        "doc-1",
        "공정 안내서",
    )

    result = build_grounded_answer(pack, max_claims=3)

    assert [citation.page_number for citation in result.citations] == [8]


def test_grounded_answer_keeps_pages_that_add_query_concepts() -> None:
    """Retain complementary pages while excluding redundant evidence."""
    pack = build_evidence_pack(
        "식각 선택비의 정의와 과식각 위험은?",
        (
            _make_hit("과식각은 하부 막 손상 위험을 높인다.", page=17, score=1.0),
            _make_hit("식각 선택비는 두 재료의 식각률 비율이다.", page=16, score=0.9),
            _make_hit("식각 장비의 일반 구성이다.", page=59, score=0.8),
        ),
        "doc-1",
        "공정 안내서",
    )

    result = build_grounded_answer(pack, max_claims=3)

    assert {citation.page_number for citation in result.citations} == {16, 17}
    assert all(citation.page_number != 59 for citation in result.citations)


def test_grounded_answer_can_select_multiple_sentences_from_one_page() -> None:
    """Preserve complementary facts that share the best evidence page."""
    pack = build_evidence_pack(
        "건식 산화와 습식 산화의 성장 속도와 막질 차이는?",
        (
            _make_hit(
                "건식 산화는 성장 속도가 느리고 막질이 치밀하다. "
                "습식 산화는 성장 속도가 빠르지만 막질은 상대적으로 낮다.",
                page=8,
            ),
            _make_hit("산화 공정의 일반 주의사항이다.", page=9),
        ),
        "doc-1",
        "공정 안내서",
    )

    result = build_grounded_answer(pack, max_claims=3)

    assert len(result.claims) == 2
    assert [citation.page_number for citation in result.citations] == [8, 8]
