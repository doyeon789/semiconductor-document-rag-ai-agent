"""Orchestrate bounded retrieval, rewrite, answer, and validation paths."""

from __future__ import annotations

from typing import Literal, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from semiconductor_rag.agent.models import (
    AgentRun,
    AgentTerminationReason,
    AgentTraceEvent,
)
from semiconductor_rag.agent.query_rewrite import rewrite_semiconductor_query
from semiconductor_rag.agent.tools import RetrievalAgentTools
from semiconductor_rag.answering import (
    EvidencePack,
    GroundedAnswer,
    build_grounded_answer,
    validate_citation,
)
from semiconductor_rag.retrieval import SearchMode

MIN_BM25_SCORE_DOMINANCE = 1.5


class AgentState(TypedDict):
    """Carry bounded agent state between explicit LangGraph nodes."""

    trace_id: UUID
    question: str
    active_query: str
    top_k: int
    max_claims: int
    max_retrieval_attempts: int
    retrieval_attempts: int
    next_mode: SearchMode
    evidence: EvidencePack | None
    answer: GroundedAnswer | None
    answer_valid: bool | None
    search_queries: tuple[str, ...]
    search_modes: tuple[SearchMode, ...]
    termination_reason: AgentTerminationReason | None
    trace: tuple[AgentTraceEvent, ...]


class RetrievalAgent:
    """Run a deterministic, bounded Agentic RAG state graph.

    Parameters
    ----------
    tools : RetrievalAgentTools
        Typed in-process retrieval and answering tools.
    """

    def __init__(self, tools: RetrievalAgentTools) -> None:
        """Compile the state graph around injected application tools."""
        self._tools = tools
        self._graph = self._build_graph()

    def run(
        self,
        question: str,
        top_k: int = 5,
        max_claims: int = 1,
        max_retrieval_attempts: int = 2,
    ) -> AgentRun:
        """Run bounded retrieval until a verified answer or abstention.

        Parameters
        ----------
        question : str
            User question.
        top_k : int, default=5
            Maximum evidence count requested from each retrieval attempt.
        max_claims : int, default=1
            Maximum claims in the final extractive answer.
        max_retrieval_attempts : int, default=2
            Hard limit including the initial retrieval attempt.

        Returns
        -------
        AgentRun
            Final grounded answer and reconstructable trajectory.

        Raises
        ------
        ValueError
            If text is blank or any configured limit is not positive.
        """
        stripped_question = question.strip()
        if not stripped_question:
            raise ValueError("question must not be blank")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if max_claims < 1:
            raise ValueError("max_claims must be positive")
        if max_retrieval_attempts < 1:
            raise ValueError("max_retrieval_attempts must be positive")

        initial_state: AgentState = {
            "trace_id": uuid4(),
            "question": stripped_question,
            "active_query": stripped_question,
            "top_k": top_k,
            "max_claims": max_claims,
            "max_retrieval_attempts": max_retrieval_attempts,
            "retrieval_attempts": 0,
            "next_mode": SearchMode.BM25,
            "evidence": None,
            "answer": None,
            "answer_valid": None,
            "search_queries": (),
            "search_modes": (),
            "termination_reason": None,
            "trace": (),
        }
        result = cast(AgentState, self._graph.invoke(initial_state))
        answer = result["answer"]
        termination_reason = result["termination_reason"]
        if answer is None or termination_reason is None:
            raise RuntimeError("agent graph ended without a final outcome")
        return AgentRun(
            trace_id=result["trace_id"],
            question=result["question"],
            answer=answer,
            retrieval_attempts=result["retrieval_attempts"],
            search_queries=result["search_queries"],
            search_modes=result["search_modes"],
            termination_reason=termination_reason,
            trace=result["trace"],
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        """Compile explicit retrieval and validation routes.

        Returns
        -------
        langgraph.graph.state.CompiledStateGraph
            Reusable bounded retrieval graph.
        """
        builder = StateGraph(AgentState)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("assess", self._assess)
        builder.add_node("rewrite", self._rewrite)
        builder.add_node("generate", self._generate)
        builder.add_node("validate", self._validate)
        builder.add_node("finalize", self._finalize)
        builder.add_node("abstain", self._abstain)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "assess")
        builder.add_conditional_edges("assess", self._route_after_assessment)
        builder.add_edge("rewrite", "retrieve")
        builder.add_edge("generate", "validate")
        builder.add_conditional_edges("validate", self._route_after_validation)
        builder.add_edge("finalize", END)
        builder.add_edge("abstain", END)
        return builder.compile()

    def _retrieve(self, state: AgentState) -> dict[str, object]:
        """Call the selected retrieval tool and record the attempt."""
        evidence = self._tools.search_evidence(
            state["active_query"],
            state["next_mode"],
            state["top_k"],
        )
        return {
            "evidence": evidence,
            "retrieval_attempts": state["retrieval_attempts"] + 1,
            "search_queries": (*state["search_queries"], state["active_query"]),
            "search_modes": (*state["search_modes"], state["next_mode"]),
            "trace": self._append_event(
                state,
                "tool.search.completed",
                query=state["active_query"],
                mode=state["next_mode"],
                detail=f"evidence_count={len(evidence.blocks)}",
            ),
        }

    def _assess(self, state: AgentState) -> dict[str, object]:
        """Record whether the latest evidence can support an answer."""
        sufficient = self._evidence_is_sufficient(state)
        return {
            "trace": self._append_event(
                state,
                "retrieval.sufficiency_checked",
                detail="sufficient" if sufficient else "insufficient",
            )
        }

    def _route_after_assessment(
        self,
        state: AgentState,
    ) -> Literal["generate", "rewrite", "abstain"]:
        """Choose answer, retry, or abstention after evidence assessment."""
        if self._evidence_is_sufficient(state):
            return "generate"
        if state["retrieval_attempts"] < state["max_retrieval_attempts"]:
            return "rewrite"
        return "abstain"

    def _rewrite(self, state: AgentState) -> dict[str, object]:
        """Expand domain aliases and select precise reranked retrieval."""
        rewrite = rewrite_semiconductor_query(state["question"])
        return {
            "active_query": rewrite.rewritten_query,
            "next_mode": SearchMode.RERANK,
            "trace": self._append_event(
                state,
                "query.rewritten",
                query=rewrite.rewritten_query,
                mode=SearchMode.RERANK,
                detail=(
                    f"added_terms={','.join(rewrite.added_terms)}"
                    if rewrite.added_terms
                    else "no_domain_alias"
                ),
            ),
        }

    def _generate(self, state: AgentState) -> dict[str, object]:
        """Build an extractive answer from the current evidence."""
        evidence = state["evidence"]
        if evidence is None:
            raise RuntimeError("generate node requires evidence")
        answer = self._tools.answer_evidence(evidence, state["max_claims"])
        return {
            "answer": answer,
            "trace": self._append_event(
                state,
                "answer.generated",
                detail=f"claim_count={len(answer.claims)}",
            ),
        }

    def _validate(self, state: AgentState) -> dict[str, object]:
        """Validate claim mappings and every citation against current evidence."""
        valid = self._answer_matches_evidence(state["answer"], state["evidence"])
        return {
            "answer_valid": valid,
            "trace": self._append_event(
                state,
                "citation.validated",
                detail="valid" if valid else "invalid",
            ),
        }

    def _route_after_validation(
        self,
        state: AgentState,
    ) -> Literal["finalize", "abstain"]:
        """Return only validated answers and abstain from invalid drafts."""
        return "finalize" if state["answer_valid"] else "abstain"

    def _finalize(self, state: AgentState) -> dict[str, object]:
        """Mark a citation-validated answer as the final outcome."""
        return {
            "termination_reason": AgentTerminationReason.ANSWER_VALIDATED,
            "trace": self._append_event(state, "agent.completed", detail="validated"),
        }

    def _abstain(self, state: AgentState) -> dict[str, object]:
        """Replace unsupported or invalid output with a safe abstention."""
        validation_failed = state["answer_valid"] is False
        reason = (
            AgentTerminationReason.ANSWER_VALIDATION_FAILED
            if validation_failed
            else AgentTerminationReason.RETRIEVAL_LIMIT_REACHED
        )
        empty_evidence = EvidencePack(query=state["active_query"], blocks=())
        return {
            "answer": build_grounded_answer(empty_evidence),
            "termination_reason": reason,
            "trace": self._append_event(
                state,
                "agent.abstained",
                detail=reason.value,
            ),
        }

    @staticmethod
    def _answer_matches_evidence(
        answer: GroundedAnswer | None,
        evidence: EvidencePack | None,
    ) -> bool:
        """Check claim links and source metadata for a generated answer."""
        if answer is None or answer.abstained or evidence is None:
            return False
        blocks_by_id = {block.evidence_id: block for block in evidence.blocks}
        citations_by_id = {
            citation.citation_id: citation for citation in answer.citations
        }
        for claim in answer.claims:
            if any(
                citation_id not in citations_by_id for citation_id in claim.citation_ids
            ):
                return False
        return all(
            citation.evidence_id in blocks_by_id
            and validate_citation(citation, blocks_by_id[citation.evidence_id])
            for citation in answer.citations
        )

    @staticmethod
    def _evidence_is_sufficient(state: AgentState) -> bool:
        """Accept precise evidence and retry ambiguous first-stage rankings."""
        evidence = state["evidence"]
        if evidence is None or not evidence.blocks:
            return False
        if state["next_mode"] is not SearchMode.BM25 or len(evidence.blocks) == 1:
            return True
        first_score = evidence.blocks[0].retrieval_score
        second_score = evidence.blocks[1].retrieval_score
        if second_score <= 0:
            return True
        return first_score / second_score >= MIN_BM25_SCORE_DOMINANCE

    @staticmethod
    def _append_event(
        state: AgentState,
        name: str,
        query: str | None = None,
        mode: SearchMode | None = None,
        detail: str | None = None,
    ) -> tuple[AgentTraceEvent, ...]:
        """Append one deterministic sequence-numbered trace event."""
        event = AgentTraceEvent(
            sequence=len(state["trace"]) + 1,
            name=name,
            query=query,
            mode=mode,
            detail=detail,
        )
        return (*state["trace"], event)
