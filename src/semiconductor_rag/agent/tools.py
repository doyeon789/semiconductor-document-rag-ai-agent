"""In-process typed tools used by the bounded retrieval agent."""

from __future__ import annotations

from typing import Protocol

from semiconductor_rag.answering import (
    EvidencePack,
    GroundedAnswer,
    build_evidence_pack,
    build_grounded_answer,
)
from semiconductor_rag.retrieval import LocalSearchService, SearchMode


class RetrievalAgentTools(Protocol):
    """Define independently testable tools required by the agent graph."""

    def search_evidence(
        self,
        query: str,
        mode: SearchMode,
        top_k: int,
    ) -> EvidencePack:
        """Search and convert ranked hits into page-grounded evidence."""
        ...

    def answer_evidence(
        self,
        evidence: EvidencePack,
        max_claims: int,
    ) -> GroundedAnswer:
        """Build an extractive answer from verified evidence."""
        ...


class LocalRetrievalAgentTools:
    """Expose search and grounded answering as typed in-process tools.

    Parameters
    ----------
    search_service : LocalSearchService
        Local sparse, dense, hybrid, and reranked retrieval service.
    document_id : str
        Stable source document identifier.
    document_title : str
        Human-readable source document title.
    """

    def __init__(
        self,
        search_service: LocalSearchService,
        document_id: str,
        document_title: str,
    ) -> None:
        """Store reusable application services and document metadata."""
        if not document_id.strip():
            raise ValueError("document_id must not be blank")
        if not document_title.strip():
            raise ValueError("document_title must not be blank")
        self._search_service = search_service
        self._document_id = document_id
        self._document_title = document_title

    def search_evidence(
        self,
        query: str,
        mode: SearchMode,
        top_k: int,
    ) -> EvidencePack:
        """Search the local corpus and create distinct page evidence.

        Parameters
        ----------
        query : str
            Active search query.
        mode : SearchMode
            Retrieval strategy selected by the agent.
        top_k : int
            Maximum ranked hits and evidence blocks.

        Returns
        -------
        EvidencePack
            Page-grounded evidence for the active query.
        """
        hits = self._search_service.search(query, mode, top_k)
        return build_evidence_pack(
            query,
            hits,
            document_id=self._document_id,
            document_title=self._document_title,
            max_evidence=top_k,
        )

    def answer_evidence(
        self,
        evidence: EvidencePack,
        max_claims: int,
    ) -> GroundedAnswer:
        """Build a citation-verified extractive answer.

        Parameters
        ----------
        evidence : EvidencePack
            Retrieved source evidence.
        max_claims : int
            Maximum answer claims.

        Returns
        -------
        GroundedAnswer
            Extractive answer or normal evidence abstention.
        """
        return build_grounded_answer(evidence, max_claims=max_claims)
