"""Create extractive answers whose citations are verified against evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semiconductor_rag.answering.evidence import (
    EvidenceBlock,
    EvidencePack,
    has_sufficient_evidence,
)
from semiconductor_rag.domain import CitationSupport
from semiconductor_rag.retrieval import tokenize_search_text

SENTENCE_PATTERN = re.compile(r"[^.!?。\n]+[.!?。]?")
CONCEPT_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*|[가-힣]{2,}")
QUESTION_CONCEPTS = frozenset(
    {
        "무엇",
        "엇인",
        "인가",
        "어떤",
        "어떻",
        "떻게",
        "어디",
        "디에",
        "에서",
        "있나",
        "설명",
        "알려",
    }
)
MIN_MARGINAL_CONCEPT_RATIO = 0.2


@dataclass(frozen=True, slots=True)
class _AnswerCandidate:
    """Pair one source sentence with its evidence and query concepts."""

    evidence_rank: int
    sentence_rank: int
    evidence: EvidenceBlock
    quote: str
    concepts: frozenset[str]


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
    if not has_sufficient_evidence(evidence_pack):
        return _build_abstention(len(evidence_pack.blocks))

    candidates = _select_answer_candidates(
        evidence_pack,
        max_claims,
        max_quote_characters,
    )
    claims: list[GroundedClaim] = []
    citations: list[GroundedCitation] = []
    for candidate in candidates:
        evidence = candidate.evidence
        quote = candidate.quote
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


def _select_answer_candidates(
    evidence_pack: EvidencePack,
    max_claims: int,
    max_quote_characters: int,
) -> tuple[_AnswerCandidate, ...]:
    """Select quotes that cover distinct query concepts without over-citing.

    Parameters
    ----------
    evidence_pack : EvidencePack
        Ranked source pages considered for answer generation.
    max_claims : int
        Maximum number of selected answer claims.
    max_quote_characters : int
        Maximum exact quote length.

    Returns
    -------
    tuple[_AnswerCandidate, ...]
        Relevance-ordered candidates that each add meaningful query coverage.
    """
    query_concepts = _extract_concepts(evidence_pack.query)
    candidates = tuple(
        _AnswerCandidate(
            evidence_rank=evidence_rank,
            sentence_rank=sentence_rank,
            evidence=evidence,
            quote=quote[:max_quote_characters].strip(),
            concepts=frozenset(
                concept for concept in query_concepts if concept in quote.casefold()
            ),
        )
        for evidence_rank, evidence in enumerate(evidence_pack.blocks)
        for sentence_rank, quote in enumerate(_split_sentences(evidence.text))
    )
    if not candidates:
        evidence = evidence_pack.blocks[0]
        quote = _select_quote(
            evidence_pack.query,
            evidence.text,
            max_quote_characters,
        )
        return (
            _AnswerCandidate(
                evidence_rank=0,
                sentence_rank=0,
                evidence=evidence,
                quote=quote,
                concepts=frozenset(),
            ),
        )
    concepts_by_evidence = {
        evidence_rank: {
            concept
            for concept in query_concepts
            if concept
            in _select_quote(
                evidence_pack.query,
                evidence.text,
                max_quote_characters,
            ).casefold()
        }
        for evidence_rank, evidence in enumerate(evidence_pack.blocks)
    }
    ranked_evidence = sorted(
        concepts_by_evidence,
        key=lambda rank: (-len(concepts_by_evidence[rank]), rank),
    )
    selected_evidence: set[int] = set()
    covered_by_evidence: set[str] = set()
    for evidence_rank in ranked_evidence:
        new_concepts = concepts_by_evidence[evidence_rank].difference(
            covered_by_evidence
        )
        if selected_evidence and (
            not query_concepts
            or len(new_concepts) / len(query_concepts) < MIN_MARGINAL_CONCEPT_RATIO
        ):
            continue
        selected_evidence.add(evidence_rank)
        covered_by_evidence.update(concepts_by_evidence[evidence_rank])
        if (
            len(selected_evidence) == max_claims
            or covered_by_evidence == query_concepts
        ):
            break

    ranked = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.evidence_rank in selected_evidence and candidate.concepts
        ),
        key=lambda candidate: (
            -len(candidate.concepts),
            candidate.evidence_rank,
            candidate.sentence_rank,
        ),
    )
    selected: list[_AnswerCandidate] = []
    covered: set[str] = set()
    for candidate in ranked:
        new_sentence_concepts = candidate.concepts.difference(covered)
        if selected and not new_sentence_concepts:
            continue
        selected.append(candidate)
        covered.update(candidate.concepts)
        if len(selected) == max_claims or covered == query_concepts:
            break
    if selected:
        return tuple(selected)
    evidence = evidence_pack.blocks[0]
    quote = _select_quote(
        evidence_pack.query,
        evidence.text,
        max_quote_characters,
    )
    return (
        _AnswerCandidate(
            evidence_rank=0,
            sentence_rank=0,
            evidence=evidence,
            quote=quote,
            concepts=frozenset(),
        ),
    )


def _split_sentences(text: str) -> tuple[str, ...]:
    """Split source text into non-empty exact sentence substrings.

    Parameters
    ----------
    text : str
        Retrieved page text.

    Returns
    -------
    tuple[str, ...]
        Sentence substrings in source order.
    """
    return tuple(
        match.group(0).strip()
        for match in SENTENCE_PATTERN.finditer(text)
        if match.group(0).strip()
    )


def _extract_concepts(value: str) -> frozenset[str]:
    """Extract stable English terms and Korean bigrams from a question.

    Parameters
    ----------
    value : str
        User question used for evidence selection.

    Returns
    -------
    frozenset[str]
        Case-folded technical terms with common question forms removed.
    """
    concepts: set[str] = set()
    for token in CONCEPT_PATTERN.findall(value.casefold()):
        if token.isascii():
            concepts.add(token)
            continue
        concepts.update(token[index : index + 2] for index in range(len(token) - 1))
    return frozenset(concepts.difference(QUESTION_CONCEPTS))


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


def _build_abstention(evidence_count: int = 0) -> GroundedAnswer:
    """Create the standard evidence-insufficient outcome.

    Parameters
    ----------
    evidence_count : int, default=0
        Number of candidate evidence blocks rejected as insufficient.

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
        evidence_count=evidence_count,
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
    sentences = _split_sentences(text)
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
