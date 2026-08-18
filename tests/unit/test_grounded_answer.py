"""Unit tests for extractive grounded answers and citation verification."""

from hashlib import sha256
from uuid import UUID

import pytest

from semiconductor_rag.answering import (
    EvidenceSufficiency,
    TerminationReason,
    build_evidence_pack,
    build_grounded_answer,
    validate_citation,
)
from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import SearchHit, SearchMode

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


def test_grounded_answer_abstains_for_weak_reranked_evidence() -> None:
    """Reject lexical overlap when the reranker finds no relevant source."""
    pack = build_evidence_pack(
        "큐비트 오류 방식",
        (_make_hit("공정 오류를 줄이는 방식", score=-1.1),),
        "doc-1",
        "공정 안내서",
        retrieval_mode=SearchMode.RERANK,
    )

    result = build_grounded_answer(pack)

    assert result.abstained is True
    assert result.evidence_count == 1
    assert result.termination_reason is TerminationReason.EVIDENCE_INSUFFICIENT


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


def test_citation_validator_rejects_wrong_page() -> None:
    """Reject a quote that is attached to a different PDF page."""
    pack = build_evidence_pack(
        "습식 산화",
        (_make_hit("습식 산화는 빠르다.", page=8),),
        "doc-1",
        "공정 안내서",
    )
    result = build_grounded_answer(pack)
    mismatched = result.citations[0].model_copy(update={"page_number": 9})

    assert validate_citation(mismatched, pack.blocks[0]) is False


def test_citation_validator_rejects_stale_document_version() -> None:
    """Reject a Citation that points to an obsolete document version."""
    pack = build_evidence_pack(
        "습식 산화",
        (_make_hit("습식 산화는 빠르다.", page=8),),
        "doc-1",
        "공정 안내서",
    )
    result = build_grounded_answer(pack)
    mismatched = result.citations[0].model_copy(
        update={"version_id": UUID("99999999-9999-4999-8999-999999999999")}
    )

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

    result = build_grounded_answer(pack, max_claims=3, max_evidence_pages=2)

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


def test_grounded_answer_rejects_non_positive_page_limit() -> None:
    """Reject an invalid source-page limit before answer selection."""
    pack = build_evidence_pack(
        "산화 조건은?",
        (_make_hit("산화 조건을 설명한다."),),
        "doc-1",
        "공정 안내서",
    )

    with pytest.raises(ValueError, match="max_evidence_pages"):
        build_grounded_answer(pack, max_evidence_pages=0)


def test_grounded_answer_keeps_strong_reranked_page_within_score_margin() -> None:
    """Do not replace strong evidence with a much weaker keyword-heavy page."""
    pack = build_evidence_pack(
        "산화 조건과 위험은?",
        (
            _make_hit("산화 공정의 직접 근거를 설명한다.", page=8, score=0.9),
            _make_hit("산화 조건과 위험을 함께 나열한다.", page=9, score=0.2),
        ),
        "doc-1",
        "공정 안내서",
        retrieval_mode=SearchMode.RERANK,
    )

    result = build_grounded_answer(pack)

    assert [citation.page_number for citation in result.citations] == [8]


def test_grounded_answer_prefers_direct_role_mapping() -> None:
    """Prefer an explicit role mapping over a generic role summary."""
    pack = build_evidence_pack(
        "이온 주입 에너지와 도즈 역할은?",
        (
            _make_hit("이온 주입 에너지와 도즈 역할을 설명한다.", page=22, score=1.0),
            _make_hit(
                "이온 주입에서 에너지 → 깊이 | 도즈 → 총 도펀트량이다.",
                page=21,
                score=0.7,
            ),
        ),
        "doc-1",
        "공정 안내서",
        retrieval_mode=SearchMode.RERANK,
    )

    result = build_grounded_answer(pack)

    assert [citation.page_number for citation in result.citations] == [21]


def test_grounded_answer_prefers_exact_cause_and_result_evidence() -> None:
    """Prefer a page that states both requested causal relation terms."""
    pack = build_evidence_pack(
        "패키지 warpage 원인과 결과는?",
        (
            _make_hit(
                "패키지 warpage 원인 분석 원칙.\n관찰 결과를 연결한다.",
                page=62,
                score=-0.3,
            ),
            _make_hit(
                "고장 모드 | 결과 | 가능한 원인\nWarpage 패키지 휨을 설명한다.",
                page=31,
                score=-0.6,
            ),
        ),
        "doc-1",
        "공정 안내서",
        retrieval_mode=SearchMode.RERANK,
    )

    result = build_grounded_answer(pack)

    assert result.citations
    assert all(citation.page_number == 31 for citation in result.citations)


def test_grounded_answer_prefers_direct_failure_path_mapping() -> None:
    """Prefer an explicit failure path even when it is ranked third."""
    pack = build_evidence_pack(
        "포토 결함이 금속배선 불량으로 이어지는 경로는?",
        (
            _make_hit(
                "가공 → 포토 결함으로 이동하는 경로를 설명한다.",
                page=7,
                score=-0.04,
            ),
            _make_hit("금속배선 결함과 전기 경로를 설명한다.", page=24, score=-0.22),
            _make_hit(
                "CROSS-PROCESS · CAUSE → EFFECT\n포토 결함의 전파를 설명한다.",
                page=62,
                score=-0.47,
            ),
        ),
        "doc-1",
        "공정 안내서",
        retrieval_mode=SearchMode.RERANK,
    )

    result = build_grounded_answer(pack)

    assert [citation.page_number for citation in result.citations] == [62]
