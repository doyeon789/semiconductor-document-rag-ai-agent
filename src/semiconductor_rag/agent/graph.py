"""Orchestrate bounded retrieval, recovery, and validation paths."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Literal, TypedDict, TypeVar, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from semiconductor_rag.agent.guardrails import classify_agent_question
from semiconductor_rag.agent.models import (
    AgentQuestionClass,
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
DEFAULT_MAX_STEPS = 14
DEFAULT_TOOL_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_REPAIR_ATTEMPTS = 1

T = TypeVar("T")


class AgentState(TypedDict):
    """Carry bounded agent state between explicit LangGraph nodes."""

    trace_id: UUID
    question: str
    question_class: AgentQuestionClass
    active_query: str
    top_k: int
    max_claims: int
    max_steps: int
    step_count: int
    max_retrieval_attempts: int
    retrieval_attempts: int
    max_repair_attempts: int
    repair_attempts: int
    tool_timeout_seconds: float
    next_mode: SearchMode
    evidence: EvidencePack | None
    answer: GroundedAnswer | None
    answer_valid: bool | None
    search_queries: tuple[str, ...]
    search_modes: tuple[SearchMode, ...]
    tool_errors: tuple[str, ...]
    last_tool_failure: AgentTerminationReason | None
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
        max_steps: int = DEFAULT_MAX_STEPS,
        tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
        max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
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
        max_steps : int, default=14
            Hard limit for non-terminal graph nodes.
        tool_timeout_seconds : float, default=45.0
            Maximum wait for one retrieval or answering tool call.
        max_repair_attempts : int, default=1
            Maximum trusted citation-repair attempts.

        Returns
        -------
        AgentRun
            Final grounded answer and reconstructable trajectory.

        Raises
        ------
        ValueError
            If text is blank or any configured limit is invalid.
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
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        if tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must not be negative")

        initial_state: AgentState = {
            "trace_id": uuid4(),
            "question": stripped_question,
            "question_class": AgentQuestionClass.DOCUMENT_QUERY,
            "active_query": stripped_question,
            "top_k": top_k,
            "max_claims": max_claims,
            "max_steps": max_steps,
            "step_count": 0,
            "max_retrieval_attempts": max_retrieval_attempts,
            "retrieval_attempts": 0,
            "max_repair_attempts": max_repair_attempts,
            "repair_attempts": 0,
            "tool_timeout_seconds": tool_timeout_seconds,
            "next_mode": SearchMode.BM25,
            "evidence": None,
            "answer": None,
            "answer_valid": None,
            "search_queries": (),
            "search_modes": (),
            "tool_errors": (),
            "last_tool_failure": None,
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
            question_class=result["question_class"],
            answer=answer,
            step_count=result["step_count"],
            retrieval_attempts=result["retrieval_attempts"],
            search_queries=result["search_queries"],
            search_modes=result["search_modes"],
            tool_errors=result["tool_errors"],
            repair_attempts=result["repair_attempts"],
            termination_reason=termination_reason,
            trace=result["trace"],
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        """Compile explicit planning, retrieval, and recovery routes.

        Returns
        -------
        langgraph.graph.state.CompiledStateGraph
            Reusable bounded retrieval graph.
        """
        builder = StateGraph(AgentState)
        builder.add_node("classify", self._classify)
        builder.add_node("plan", self._plan)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("gather", self._gather)
        builder.add_node("assess", self._assess)
        builder.add_node("rewrite", self._rewrite)
        builder.add_node("generate", self._generate)
        builder.add_node("validate", self._validate)
        builder.add_node("repair", self._repair)
        builder.add_node("finalize", self._finalize)
        builder.add_node("abstain", self._abstain)
        builder.add_edge(START, "classify")
        builder.add_conditional_edges("classify", self._route_after_classification)
        builder.add_conditional_edges("plan", self._route_after_plan)
        builder.add_conditional_edges("retrieve", self._route_after_retrieval)
        builder.add_conditional_edges("gather", self._route_after_gather)
        builder.add_conditional_edges("assess", self._route_after_assessment)
        builder.add_conditional_edges("rewrite", self._route_after_rewrite)
        builder.add_conditional_edges("generate", self._route_after_generation)
        builder.add_conditional_edges("validate", self._route_after_validation)
        builder.add_conditional_edges("repair", self._route_after_repair)
        builder.add_edge("finalize", END)
        builder.add_edge("abstain", END)
        return builder.compile()

    def _classify(self, state: AgentState) -> dict[str, object]:
        """Block control-seeking input before any document tool call."""
        question_class = classify_agent_question(state["question"])
        return {
            "question_class": question_class,
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                "question.classified",
                detail=question_class.value,
            ),
        }

    def _plan(self, state: AgentState) -> dict[str, object]:
        """Choose the fast first-stage retrieval plan."""
        return {
            "active_query": state["question"],
            "next_mode": SearchMode.BM25,
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                "retrieval.planned",
                query=state["question"],
                mode=SearchMode.BM25,
                detail="fallback=rerank",
            ),
        }

    def _retrieve(self, state: AgentState) -> dict[str, object]:
        """Call the selected retrieval tool within its time budget."""
        evidence: EvidencePack
        failure: AgentTerminationReason | None = None
        event_name = "tool.search.completed"
        detail: str
        errors = state["tool_errors"]
        try:
            evidence = self._call_with_timeout(
                lambda: self._tools.search_evidence(
                    state["active_query"],
                    state["next_mode"],
                    state["top_k"],
                ),
                state["tool_timeout_seconds"],
            )
            detail = f"evidence_count={len(evidence.blocks)}"
        except FutureTimeoutError:
            evidence = EvidencePack(query=state["active_query"], blocks=())
            failure = AgentTerminationReason.TOOL_TIMEOUT
            event_name = "tool.search.timed_out"
            detail = f"timeout_seconds={state['tool_timeout_seconds']:g}"
            errors = (*errors, "search:timeout")
        except Exception as exc:
            evidence = EvidencePack(query=state["active_query"], blocks=())
            failure = AgentTerminationReason.TOOL_ERROR
            event_name = "tool.search.failed"
            error_name = type(exc).__name__
            detail = f"error_type={error_name}"
            errors = (*errors, f"search:{error_name}")
        return {
            "evidence": evidence,
            "last_tool_failure": failure,
            "tool_errors": errors,
            "retrieval_attempts": state["retrieval_attempts"] + 1,
            "search_queries": (*state["search_queries"], state["active_query"]),
            "search_modes": (*state["search_modes"], state["next_mode"]),
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                event_name,
                query=state["active_query"],
                mode=state["next_mode"],
                detail=detail,
            ),
        }

    def _gather(self, state: AgentState) -> dict[str, object]:
        """Record the evidence pages selected by the current retrieval."""
        evidence = state["evidence"]
        pages = (
            ()
            if evidence is None
            else tuple(block.page_number for block in evidence.blocks)
        )
        page_detail = ",".join(str(page) for page in pages) or "none"
        return {
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                "evidence.gathered",
                detail=f"pages={page_detail}",
            ),
        }

    def _assess(self, state: AgentState) -> dict[str, object]:
        """Record whether the latest evidence can support an answer."""
        sufficient = self._evidence_is_sufficient(state)
        return {
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                "retrieval.sufficiency_checked",
                detail="sufficient" if sufficient else "insufficient",
            ),
        }

    def _rewrite(self, state: AgentState) -> dict[str, object]:
        """Expand domain aliases and select precise reranked retrieval."""
        rewrite = rewrite_semiconductor_query(state["question"])
        return {
            "active_query": rewrite.rewritten_query,
            "next_mode": SearchMode.RERANK,
            "step_count": state["step_count"] + 1,
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
        """Build an extractive answer within the tool time budget."""
        evidence = state["evidence"]
        if evidence is None:
            raise RuntimeError("generate node requires evidence")
        answer: GroundedAnswer | None = None
        failure: AgentTerminationReason | None = None
        errors = state["tool_errors"]
        event_name = "answer.generated"
        detail: str
        try:
            answer = self._call_with_timeout(
                lambda: self._tools.answer_evidence(evidence, state["max_claims"]),
                state["tool_timeout_seconds"],
            )
            detail = f"claim_count={len(answer.claims)}"
        except FutureTimeoutError:
            failure = AgentTerminationReason.TOOL_TIMEOUT
            event_name = "tool.answer.timed_out"
            detail = f"timeout_seconds={state['tool_timeout_seconds']:g}"
            errors = (*errors, "answer:timeout")
        except Exception as exc:
            failure = AgentTerminationReason.TOOL_ERROR
            event_name = "tool.answer.failed"
            error_name = type(exc).__name__
            detail = f"error_type={error_name}"
            errors = (*errors, f"answer:{error_name}")
        return {
            "answer": answer,
            "last_tool_failure": failure,
            "tool_errors": errors,
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(state, event_name, detail=detail),
        }

    def _validate(self, state: AgentState) -> dict[str, object]:
        """Validate claim mappings and every citation against current evidence."""
        valid = self._answer_matches_evidence(state["answer"], state["evidence"])
        return {
            "answer_valid": valid,
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(
                state,
                "citation.validated",
                detail="valid" if valid else "invalid",
            ),
        }

    def _repair(self, state: AgentState) -> dict[str, object]:
        """Rebuild one invalid draft directly from trusted evidence."""
        evidence = state["evidence"]
        if evidence is None:
            raise RuntimeError("repair node requires evidence")
        answer: GroundedAnswer | None = None
        failure: AgentTerminationReason | None = None
        errors = state["tool_errors"]
        detail: str
        try:
            answer = build_grounded_answer(evidence, max_claims=state["max_claims"])
            detail = f"claim_count={len(answer.claims)}"
        except Exception as exc:
            failure = AgentTerminationReason.TOOL_ERROR
            error_name = type(exc).__name__
            detail = f"error_type={error_name}"
            errors = (*errors, f"repair:{error_name}")
        return {
            "answer": answer,
            "answer_valid": None,
            "last_tool_failure": failure,
            "tool_errors": errors,
            "repair_attempts": state["repair_attempts"] + 1,
            "step_count": state["step_count"] + 1,
            "trace": self._append_event(state, "answer.repaired", detail=detail),
        }

    def _route_after_classification(
        self,
        state: AgentState,
    ) -> Literal["plan", "abstain"]:
        """Stop unsafe input before planning or enforce the step budget."""
        if state["question_class"] is AgentQuestionClass.PROMPT_INJECTION:
            return "abstain"
        return "abstain" if self._step_limit_reached(state) else "plan"

    def _route_after_plan(
        self,
        state: AgentState,
    ) -> Literal["retrieve", "abstain"]:
        """Start retrieval only while the step budget remains."""
        return "abstain" if self._step_limit_reached(state) else "retrieve"

    def _route_after_retrieval(
        self,
        state: AgentState,
    ) -> Literal["gather", "abstain"]:
        """Gather completed tool output while the step budget remains."""
        return "abstain" if self._step_limit_reached(state) else "gather"

    def _route_after_gather(
        self,
        state: AgentState,
    ) -> Literal["assess", "abstain"]:
        """Assess gathered evidence while the step budget remains."""
        return "abstain" if self._step_limit_reached(state) else "assess"

    def _route_after_assessment(
        self,
        state: AgentState,
    ) -> Literal["generate", "rewrite", "abstain"]:
        """Choose answer, retry, or abstention after evidence assessment."""
        if self._evidence_is_sufficient(state):
            return "generate" if not self._step_limit_reached(state) else "abstain"
        if self._step_limit_reached(state):
            return "abstain"
        if state["retrieval_attempts"] < state["max_retrieval_attempts"]:
            return "rewrite"
        return "abstain"

    def _route_after_rewrite(
        self,
        state: AgentState,
    ) -> Literal["retrieve", "abstain"]:
        """Run the rewritten query while the step budget remains."""
        return "abstain" if self._step_limit_reached(state) else "retrieve"

    def _route_after_generation(
        self,
        state: AgentState,
    ) -> Literal["validate", "abstain"]:
        """Validate a draft while the step budget remains."""
        return "abstain" if self._step_limit_reached(state) else "validate"

    def _route_after_validation(
        self,
        state: AgentState,
    ) -> Literal["finalize", "repair", "abstain"]:
        """Return, repair once, or safely abstain after validation."""
        if state["answer_valid"]:
            return "finalize"
        if self._step_limit_reached(state):
            return "abstain"
        if (
            state["evidence"] is not None
            and bool(state["evidence"].blocks)
            and state["repair_attempts"] < state["max_repair_attempts"]
        ):
            return "repair"
        return "abstain"

    def _route_after_repair(
        self,
        state: AgentState,
    ) -> Literal["validate", "abstain"]:
        """Revalidate repaired output while the step budget remains."""
        if state["answer"] is None or self._step_limit_reached(state):
            return "abstain"
        return "validate"

    def _finalize(self, state: AgentState) -> dict[str, object]:
        """Mark a citation-validated answer as the final outcome."""
        return {
            "termination_reason": AgentTerminationReason.ANSWER_VALIDATED,
            "trace": self._append_event(state, "agent.completed", detail="validated"),
        }

    def _abstain(self, state: AgentState) -> dict[str, object]:
        """Replace unsupported or unsafe output with a safe abstention."""
        if state["question_class"] is AgentQuestionClass.PROMPT_INJECTION:
            reason = AgentTerminationReason.PROMPT_INJECTION_DETECTED
        elif state["last_tool_failure"] is not None:
            reason = state["last_tool_failure"]
        elif state["answer_valid"] is False:
            reason = AgentTerminationReason.ANSWER_VALIDATION_FAILED
        elif self._step_limit_reached(state):
            reason = AgentTerminationReason.STEP_LIMIT_REACHED
        else:
            reason = AgentTerminationReason.RETRIEVAL_LIMIT_REACHED
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
        referenced_citation_ids: set[UUID] = set()
        for claim in answer.claims:
            if any(
                citation_id not in citations_by_id for citation_id in claim.citation_ids
            ):
                return False
            referenced_citation_ids.update(claim.citation_ids)
            if not any(
                claim.text == citations_by_id[citation_id].quote
                for citation_id in claim.citation_ids
            ):
                return False
        return referenced_citation_ids == set(citations_by_id) and all(
            citation.evidence_id in blocks_by_id
            and validate_citation(citation, blocks_by_id[citation.evidence_id])
            for citation in answer.citations
        )

    @staticmethod
    def _evidence_is_sufficient(state: AgentState) -> bool:
        """Accept precise evidence and retry ambiguous first-stage rankings."""
        evidence = state["evidence"]
        if state["last_tool_failure"] is not None or evidence is None:
            return False
        if not evidence.blocks:
            return False
        if state["next_mode"] is not SearchMode.BM25 or len(evidence.blocks) == 1:
            return True
        first_score = evidence.blocks[0].retrieval_score
        second_score = evidence.blocks[1].retrieval_score
        if second_score <= 0:
            return True
        return first_score / second_score >= MIN_BM25_SCORE_DOMINANCE

    @staticmethod
    def _step_limit_reached(state: AgentState) -> bool:
        """Return whether another non-terminal node would exceed the budget."""
        return state["step_count"] >= state["max_steps"]

    @staticmethod
    def _call_with_timeout(operation: Callable[[], T], timeout_seconds: float) -> T:
        """Run one tool call with a bounded caller wait.

        Parameters
        ----------
        operation : collections.abc.Callable
            Zero-argument tool invocation.
        timeout_seconds : float
            Positive caller wait limit.

        Returns
        -------
        T
            Tool result.

        Raises
        ------
        concurrent.futures.TimeoutError
            If the tool does not finish within the limit.
        Exception
            Any exception raised by the tool implementation.
        """
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-tool")
        future = executor.submit(operation)
        try:
            return future.result(timeout=timeout_seconds)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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
