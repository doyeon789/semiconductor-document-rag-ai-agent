"""Build compact page-grounded evidence packs from ranked search hits."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.retrieval import SearchHit


class EvidenceBlock(BaseModel):
    """Represent one answerable source block on a traceable PDF page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    version_id: UUID
    chunk_id: UUID
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    retrieval_score: float


class EvidencePack(BaseModel):
    """Carry ranked page evidence for one question into answer generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)
    blocks: tuple[EvidenceBlock, ...]


def build_evidence_pack(
    query: str,
    hits: Sequence[SearchHit],
    document_id: str,
    document_title: str,
    max_evidence: int = 5,
) -> EvidencePack:
    """Select the strongest distinct PDF pages as answer evidence.

    Parameters
    ----------
    query : str
        User question that produced the search hits.
    hits : collections.abc.Sequence[SearchHit]
        Ranked page-traceable search results.
    document_id : str
        Stable source document identifier.
    document_title : str
        Human-readable source document title.
    max_evidence : int, default=5
        Maximum number of distinct page blocks to retain.

    Returns
    -------
    EvidencePack
        Ordered evidence blocks with stable request-local identifiers.

    Raises
    ------
    ValueError
        If text metadata is blank, ``max_evidence`` is not positive, or a
        search hit spans multiple pages.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if not document_id.strip():
        raise ValueError("document_id must not be blank")
    if not document_title.strip():
        raise ValueError("document_title must not be blank")
    if max_evidence < 1:
        raise ValueError("max_evidence must be positive")

    blocks: list[EvidenceBlock] = []
    seen_pages: set[tuple[UUID, int]] = set()
    for hit in hits:
        if hit.chunk.page_start != hit.chunk.page_end:
            raise ValueError("evidence chunks must remain within one PDF page")
        page_key = (hit.chunk.version_id, hit.chunk.page_start)
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        blocks.append(
            EvidenceBlock(
                evidence_id=f"E{len(blocks) + 1}",
                document_id=document_id,
                document_title=document_title,
                version_id=hit.chunk.version_id,
                chunk_id=hit.chunk.chunk_id,
                page_number=hit.chunk.page_start,
                text=hit.chunk.text,
                retrieval_score=hit.score,
            )
        )
        if len(blocks) == max_evidence:
            break
    return EvidencePack(query=query, blocks=tuple(blocks))
