"""Evaluate grounded answers, citations, abstention, and agent trajectories."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from statistics import mean
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.agent import AgentRun, AgentTerminationReason
from semiconductor_rag.evaluation.retrieval import RetrievalCase
from semiconductor_rag.retrieval import SearchMode, tokenize_search_text

NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:\s*[%℃°A-Za-zΩ/]+)?")
KOREAN_TERM_PATTERN = re.compile(r"^[가-힣]{4,}$")
TECHNICAL_FACT_ALIASES = {
    "sheet resistance": ("sheet r", "시트저항"),
}


class EvaluationAgent(Protocol):
    """Define the bounded Agent behavior required by quality evaluation."""

    def run(
        self,
        question: str,
        top_k: int = 5,
        max_claims: int = 1,
        max_retrieval_attempts: int = 2,
    ) -> AgentRun:
        """Return one grounded answer and reconstructable trajectory."""
        ...


class AnswerCaseResult(BaseModel):
    """Record answer and trajectory quality for one evaluation case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    language: str
    intent: str
    answerable: bool
    abstained: bool
    passed: bool
    failure_reasons: list[str]
    fact_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    numeric_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    cited_pages: list[int]
    page_match_accuracy: float = Field(ge=0.0, le=1.0)
    quote_match_rate: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    termination_correct: bool
    trajectory_correct: bool
    termination_reason: AgentTerminationReason
    search_modes: list[SearchMode]
    trace_events: list[str]
    retrieval_attempts: int = Field(ge=0)
    step_count: int = Field(ge=1)
    tool_error_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)


class QualityEvaluation(BaseModel):
    """Aggregate answer, citation, abstention, and Agent metrics."""

    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    pass_rate: float = Field(ge=0.0, le=1.0)
    required_fact_coverage: float = Field(ge=0.0, le=1.0)
    numeric_accuracy: float = Field(ge=0.0, le=1.0)
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    page_match_accuracy: float = Field(ge=0.0, le=1.0)
    quote_match_rate: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    abstention_precision: float = Field(ge=0.0, le=1.0)
    abstention_recall: float = Field(ge=0.0, le=1.0)
    unsafe_answer_rate: float = Field(ge=0.0, le=1.0)
    false_abstention_rate: float = Field(ge=0.0, le=1.0)
    termination_accuracy: float = Field(ge=0.0, le=1.0)
    trajectory_accuracy: float = Field(ge=0.0, le=1.0)
    retry_success_rate: float = Field(ge=0.0, le=1.0)
    tool_error_recovery_rate: float = Field(ge=0.0, le=1.0)
    unnecessary_tool_call_rate: float = Field(ge=0.0, le=1.0)
    average_retrieval_attempts: float = Field(ge=0.0)
    average_tool_calls: float = Field(ge=0.0)
    average_steps: float = Field(ge=1.0)
    mean_latency_ms: float = Field(ge=0.0)
    max_step_violation_count: int = Field(ge=0)
    cases: list[AnswerCaseResult]


def evaluate_quality(
    agent: EvaluationAgent,
    cases: Sequence[RetrievalCase],
    page_texts: Mapping[int, str],
    top_k: int = 5,
    max_claims: int = 3,
) -> QualityEvaluation:
    """Evaluate answer and Agent quality over a validated case sequence.

    Parameters
    ----------
    agent : EvaluationAgent
        Agent implementation under evaluation.
    cases : collections.abc.Sequence[RetrievalCase]
        Answerable, unanswerable, and safety evaluation cases.
    page_texts : collections.abc.Mapping[int, str]
        One-based PDF page text used for independent quote verification.
    top_k : int, default=5
        Evidence count requested from each retrieval attempt.
    max_claims : int, default=3
        Maximum extractive claims requested from the Agent.

    Returns
    -------
    QualityEvaluation
        Aggregate metrics and per-case diagnostics.

    Raises
    ------
    ValueError
        If cases are empty or either limit is not positive.
    """
    if not cases:
        raise ValueError("cases must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if max_claims < 1:
        raise ValueError("max_claims must be positive")

    results = [
        _evaluate_answer_case(agent, case, page_texts, top_k, max_claims)
        for case in cases
    ]
    answerable = [result for result in results if result.answerable]
    unanswerable = [result for result in results if not result.answerable]
    abstained = [result for result in results if result.abstained]
    retry_cases = [result for result in results if result.retrieval_attempts > 1]
    tool_error_cases = [result for result in results if result.tool_error_count > 0]
    expected_mode_cases = [
        (case, result)
        for case, result in zip(cases, results, strict=True)
        if case.expected_search_modes
    ]
    unnecessary_calls = sum(
        len(result.search_modes) > len(case.expected_search_modes)
        for case, result in expected_mode_cases
    )
    return QualityEvaluation(
        case_count=len(results),
        pass_rate=mean(float(result.passed) for result in results),
        required_fact_coverage=_mean_optional(results, "fact_coverage"),
        numeric_accuracy=_mean_optional(results, "numeric_accuracy"),
        citation_precision=_mean_answerable(answerable, "citation_precision"),
        citation_coverage=_mean_answerable(answerable, "citation_coverage"),
        page_match_accuracy=_mean_answerable(answerable, "page_match_accuracy"),
        quote_match_rate=_mean_answerable(answerable, "quote_match_rate"),
        faithfulness=_mean_answerable(answerable, "faithfulness"),
        abstention_precision=_safe_ratio(
            sum(not result.answerable for result in abstained),
            len(abstained),
        ),
        abstention_recall=_safe_ratio(
            sum(result.abstained for result in unanswerable),
            len(unanswerable),
        ),
        unsafe_answer_rate=_safe_ratio(
            sum(not result.abstained for result in unanswerable),
            len(unanswerable),
        ),
        false_abstention_rate=_safe_ratio(
            sum(result.abstained for result in answerable),
            len(answerable),
        ),
        termination_accuracy=mean(
            float(result.termination_correct) for result in results
        ),
        trajectory_accuracy=mean(
            float(result.trajectory_correct) for result in results
        ),
        retry_success_rate=_safe_ratio(
            sum(
                result.termination_reason is AgentTerminationReason.ANSWER_VALIDATED
                for result in retry_cases
            ),
            len(retry_cases),
        ),
        tool_error_recovery_rate=_safe_ratio(
            sum(
                result.termination_reason is AgentTerminationReason.ANSWER_VALIDATED
                for result in tool_error_cases
            ),
            len(tool_error_cases),
        ),
        unnecessary_tool_call_rate=_safe_ratio(
            unnecessary_calls,
            len(expected_mode_cases),
        ),
        average_retrieval_attempts=mean(
            result.retrieval_attempts for result in results
        ),
        average_tool_calls=mean(len(result.search_modes) for result in results),
        average_steps=mean(result.step_count for result in results),
        mean_latency_ms=mean(result.latency_ms for result in results),
        max_step_violation_count=sum(result.step_count > 14 for result in results),
        cases=results,
    )


def _evaluate_answer_case(
    agent: EvaluationAgent,
    case: RetrievalCase,
    page_texts: Mapping[int, str],
    top_k: int,
    max_claims: int,
) -> AnswerCaseResult:
    """Run and score one answer, citation, and trajectory case."""
    started_at = perf_counter()
    run = agent.run(case.query, top_k=top_k, max_claims=max_claims)
    latency_ms = (perf_counter() - started_at) * 1_000
    answer_text = run.answer.answer or ""
    citation_ids = {citation.citation_id for citation in run.answer.citations}
    linked_claims = [
        claim
        for claim in run.answer.claims
        if claim.citation_ids and set(claim.citation_ids).issubset(citation_ids)
    ]
    valid_quotes = [
        citation
        for citation in run.answer.citations
        if citation.quote in page_texts.get(citation.page_number, "")
    ]
    page_matches = [
        citation
        for citation in run.answer.citations
        if citation.page_number in case.expected_pages
    ]
    faithful_claims = [
        claim
        for claim in linked_claims
        if any(
            claim.text == citation.quote
            for citation in run.answer.citations
            if citation.citation_id in claim.citation_ids
        )
    ]
    citation_count = len(run.answer.citations)
    claim_count = len(run.answer.claims)
    fact_coverage = (
        _coverage(case.required_facts, answer_text) if case.required_facts else None
    )
    numeric_accuracy = (
        _coverage(case.required_numbers, answer_text, normalize_numbers=True)
        if case.required_numbers
        else None
    )
    expected_termination = case.expected_termination_reason or (
        AgentTerminationReason.ANSWER_VALIDATED
        if case.answerable
        else AgentTerminationReason.RETRIEVAL_LIMIT_REACHED
    )
    actual_events = [event.name for event in run.trace]
    modes_correct = not case.expected_search_modes or list(run.search_modes) == list(
        case.expected_search_modes
    )
    events_correct = all(event in actual_events for event in case.expected_events)
    trajectory_correct = modes_correct and events_correct
    termination_correct = run.termination_reason is expected_termination
    citation_precision = _safe_ratio(len(valid_quotes), citation_count)
    citation_coverage = _safe_ratio(len(linked_claims), claim_count)
    page_match_accuracy = _safe_ratio(len(page_matches), citation_count)
    quote_match_rate = _safe_ratio(len(valid_quotes), citation_count)
    faithfulness = _safe_ratio(len(faithful_claims), claim_count)

    failure_reasons: list[str] = []
    if case.answerable and run.answer.abstained:
        failure_reasons.append("false_abstention")
    if not case.answerable and not run.answer.abstained:
        failure_reasons.append("unsafe_answer")
    if case.answerable and citation_count == 0:
        failure_reasons.append("missing_citation")
    if case.answerable and page_match_accuracy < 1:
        failure_reasons.append("wrong_page")
    if case.answerable and quote_match_rate < 1:
        failure_reasons.append("quote_mismatch")
    if fact_coverage is not None and fact_coverage < 1:
        failure_reasons.append("missing_required_fact")
    if numeric_accuracy is not None and numeric_accuracy < 1:
        failure_reasons.append("numeric_mismatch")
    if not termination_correct:
        failure_reasons.append("wrong_termination")
    if not trajectory_correct:
        failure_reasons.append("wrong_trajectory")

    return AnswerCaseResult(
        id=case.id,
        language=case.language,
        intent=case.intent,
        answerable=case.answerable,
        abstained=run.answer.abstained,
        passed=not failure_reasons,
        failure_reasons=failure_reasons,
        fact_coverage=fact_coverage,
        numeric_accuracy=numeric_accuracy,
        citation_precision=citation_precision,
        citation_coverage=citation_coverage,
        cited_pages=[citation.page_number for citation in run.answer.citations],
        page_match_accuracy=page_match_accuracy,
        quote_match_rate=quote_match_rate,
        faithfulness=faithfulness,
        termination_correct=termination_correct,
        trajectory_correct=trajectory_correct,
        termination_reason=run.termination_reason,
        search_modes=list(run.search_modes),
        trace_events=actual_events,
        retrieval_attempts=run.retrieval_attempts,
        step_count=run.step_count,
        tool_error_count=len(run.tool_errors),
        latency_ms=latency_ms,
    )


def _coverage(
    expected_values: Sequence[str],
    answer_text: str,
    normalize_numbers: bool = False,
) -> float:
    """Return the fraction of required values represented in an answer."""
    if normalize_numbers:
        answer_values = {
            _normalize_number(value) for value in NUMBER_PATTERN.findall(answer_text)
        }
        return mean(
            float(_normalize_number(value) in answer_values)
            for value in expected_values
        )
    return mean(float(_fact_present(value, answer_text)) for value in expected_values)


def _fact_present(required_fact: str, answer_text: str) -> bool:
    """Match a required fact despite common Korean particles."""
    normalized_fact = " ".join(required_fact.casefold().split())
    normalized_answer = " ".join(answer_text.casefold().split())
    if normalized_fact in normalized_answer:
        return True
    compact_answer = "".join(normalized_answer.split())
    if "".join(normalized_fact.split()) in compact_answer:
        return True
    aliases = TECHNICAL_FACT_ALIASES.get(normalized_fact, ())
    if any("".join(alias.split()) in compact_answer for alias in aliases):
        return True
    if KOREAN_TERM_PATTERN.fullmatch(normalized_fact):
        fragments = tuple(
            normalized_fact[index : index + 2]
            for index in range(0, len(normalized_fact), 2)
        )
        if all(fragment in compact_answer for fragment in fragments):
            return True
    fact_tokens = {
        token
        for token in tokenize_search_text(required_fact)
        if len(token) <= 2 or not any("가" <= character <= "힣" for character in token)
    }
    answer_tokens = set(tokenize_search_text(answer_text))
    return bool(fact_tokens) and fact_tokens.issubset(answer_tokens)


def _normalize_number(value: str) -> str:
    """Normalize spacing and decimal separators in one numeric expression."""
    return "".join(value.casefold().replace(",", ".").split())


def _mean_optional(results: Sequence[AnswerCaseResult], field: str) -> float:
    """Average an optional metric over cases that define it."""
    values = [getattr(result, field) for result in results]
    present_values = [value for value in values if value is not None]
    return 1.0 if not present_values else mean(present_values)


def _mean_answerable(
    results: Sequence[AnswerCaseResult],
    field: str,
) -> float:
    """Average a citation metric over answerable cases."""
    return (
        0.0
        if not results
        else mean(float(getattr(result, field)) for result in results)
    )


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Return a bounded ratio and zero when the denominator is empty."""
    return 0.0 if denominator == 0 else numerator / denominator
