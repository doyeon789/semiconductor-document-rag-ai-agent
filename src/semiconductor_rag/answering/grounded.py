"""Create extractive answers whose citations are verified against evidence."""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semiconductor_rag.answering.evidence import EvidenceBlock, EvidencePack
from semiconductor_rag.domain import CitationSupport
from semiconductor_rag.retrieval import tokenize_search_text

SENTENCE_PATTERN = re.compile(r"[^.!?。\n]+[.!?。]?")


class EvidenceSufficiency(StrEnum):
    """Describe whether retrieved evidence can support an answer."""

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class TerminationReason(StrEnum):
    """Describe why grounded answer construction stopped."""

    ANSWER_VALIDATED = "ANSWER_VALIDATED"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"


class AbstentionReason(BaseModel):
    """Explain why the system refused to produce an unsupported answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = "EVIDENCE_INSUFFICIENT"
    message: str = "등록된 문서에서 질문을 뒷받침할 근거를 찾지 못했습니다."


class GroundedClaim(BaseModel):
    """Represent one extractive answer statement and its citation links."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: UUID
    text: str = Field(min_length=1)
    citation_ids: tuple[UUID, ...] = Field(min_length=1)
    inference: bool = False


class GroundedCitation(BaseModel):
    """Connect an answer claim to an exact quote on a versioned PDF page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: UUID
    claim_id: UUID
    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    chunk_id: UUID
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    version_id: UUID
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1)
    support: CitationSupport = CitationSupport.SUPPORTS
    validation_score: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedAnswer(BaseModel):
    """Return either verified extractive claims or an explicit abstention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str | None
    abstained: bool
    abstention_reason: AbstentionReason | None
    claims: tuple[GroundedClaim, ...]
    citations: tuple[GroundedCitation, ...]
    evidence_count: int = Field(ge=0)
    sufficiency: EvidenceSufficiency
    termination_reason: TerminationReason

    @model_validator(mode="after")
    def validate_outcome(self) -> GroundedAnswer:
        """Keep answer and abstention fields mutually consistent.

        Returns
        -------
        GroundedAnswer
            Validated answer outcome.

        Raises
        ------
        ValueError
            If an answer contains incompatible answer and abstention fields.
        """
        if self.abstained:
            if self.answer is not None or self.claims or self.citations:
                raise ValueError(
                    "abstained answers must not contain claims or citations"
                )
            if self.abstention_reason is None:
                raise ValueError("abstained answers require an abstention reason")
        elif self.answer is None or not self.claims or not self.citations:
            raise ValueError("grounded answers require text, claims, and citations")
        return self


def build_grounded_answer(
    evidence_pack: EvidencePack,
    max_claims: int = 3,
    max_quote_characters: int = 320,
) -> GroundedAnswer:
    """Create a citation-verified extractive answer from retrieved evidence.

    Parameters
    ----------
    evidence_pack : EvidencePack
        Ranked page evidence for one question.
    max_claims : int, default=3
        Maximum number of page-grounded claims to return.
    max_quote_characters : int, default=320
        Maximum characters retained from each exact source sentence.

    Returns
    -------
    GroundedAnswer
        Verified answer or a structured evidence-insufficient abstention.

    Raises
    ------
    ValueError
        If either configured limit is not positive or citation verification
        fails unexpectedly.
    """
    if max_claims < 1:
        raise ValueError("max_claims must be positive")
    if max_quote_characters < 1:
        raise ValueError("max_quote_characters must be positive")
    if not evidence_pack.blocks:
        return _build_abstention()

    claims: list[GroundedClaim] = []
    citations: list[GroundedCitation] = []
    for evidence in evidence_pack.blocks[:max_claims]:
        quote = _select_quote(
            evidence_pack.query,
            evidence.text,
            max_quote_characters,
        )
        claim_id = uuid5(
            NAMESPACE_URL,
            f"claim:{evidence_pack.query}:{evidence.evidence_id}:{quote}",
        )
        citation_id = uuid5(NAMESPACE_URL, f"citation:{claim_id}:{evidence.chunk_id}")
        citation = GroundedCitation(
            citation_id=citation_id,
            claim_id=claim_id,
            evidence_id=evidence.evidence_id,
            chunk_id=evidence.chunk_id,
            document_id=evidence.document_id,
            document_title=evidence.document_title,
            version_id=evidence.version_id,
            page_number=evidence.page_number,
            quote=quote,
        )
        if not validate_citation(citation, evidence):
            raise ValueError("generated citation does not match its source evidence")
        claims.append(
            GroundedClaim(
                claim_id=claim_id,
                text=quote,
                citation_ids=(citation_id,),
            )
        )
        citations.append(citation)

    answer_lines = [
        f"- {claim.text} ({citation.document_title}, p.{citation.page_number})"
        for claim, citation in zip(claims, citations, strict=True)
    ]
    return GroundedAnswer(
        answer="\n".join(answer_lines),
        abstained=False,
        abstention_reason=None,
        claims=tuple(claims),
        citations=tuple(citations),
        evidence_count=len(evidence_pack.blocks),
        sufficiency=EvidenceSufficiency.SUFFICIENT,
        termination_reason=TerminationReason.ANSWER_VALIDATED,
    )


def validate_citation(
    citation: GroundedCitation,
    evidence: EvidenceBlock,
) -> bool:
    """Check that a citation points to and quotes its exact evidence block.

    Parameters
    ----------
    citation : GroundedCitation
        Candidate answer citation.
    evidence : EvidenceBlock
        Retrieved source block the citation claims to use.

    Returns
    -------
    bool
        ``True`` when identifiers, page metadata, and quote all match.
    """
    return (
        citation.evidence_id == evidence.evidence_id
        and citation.chunk_id == evidence.chunk_id
        and citation.document_id == evidence.document_id
        and citation.version_id == evidence.version_id
        and citation.page_number == evidence.page_number
        and citation.quote in evidence.text
    )


def _build_abstention() -> GroundedAnswer:
    """Create the standard evidence-insufficient outcome.

    Returns
    -------
    GroundedAnswer
        Empty answer with a structured abstention reason.
    """
    return GroundedAnswer(
        answer=None,
        abstained=True,
        abstention_reason=AbstentionReason(),
        claims=(),
        citations=(),
        evidence_count=0,
        sufficiency=EvidenceSufficiency.INSUFFICIENT,
        termination_reason=TerminationReason.EVIDENCE_INSUFFICIENT,
    )


def _select_quote(query: str, text: str, max_characters: int) -> str:
    """Select the exact source sentence with the strongest query overlap.

    Parameters
    ----------
    query : str
        User question.
    text : str
        Retrieved source text.
    max_characters : int
        Maximum returned quote length.

    Returns
    -------
    str
        Exact substring copied from the source text.
    """
    sentences = tuple(
        match.group(0).strip()
        for match in SENTENCE_PATTERN.finditer(text)
        if match.group(0).strip()
    )
    if not sentences:
        return text[:max_characters].strip()
    query_tokens = set(tokenize_search_text(query))
    best_sentence = max(
        sentences,
        key=lambda sentence: len(
            query_tokens.intersection(tokenize_search_text(sentence))
        ),
    )
    return best_sentence[:max_characters].strip()
