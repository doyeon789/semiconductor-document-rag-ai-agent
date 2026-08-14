"""Unit tests for retrieval and Evidence failure classification."""

from __future__ import annotations

import pytest

from semiconductor_rag.agent import AgentTerminationReason
from semiconductor_rag.evaluation import (
    AnswerCaseResult,
    QualityEvaluation,
    RetrievalCaseResult,
    RetrievalEvaluation,
    RetrievalFailureType,
    analyze_retrieval_failures,
)
from semiconductor_rag.retrieval import SearchMode


def _retrieval_case(
    case_id: str,
    expected_pages: list[int],
    retrieved_pages: list[int],
) -> RetrievalCaseResult:
    """Create one ranking result from page lists.

    Parameters
    ----------
    case_id : str
        Stable evaluation question identifier.
    expected_pages : list[int]
        Gold PDF pages.
    retrieved_pages : list[int]
        Ranked pages returned by one search mode.

    Returns
    -------
    RetrievalCaseResult
        Minimal valid ranking result for classification.
    """
    expected = set(expected_pages)
    first_rank = next(
        (
            rank
            for rank, page_number in enumerate(retrieved_pages, start=1)
            if page_number in expected
        ),
        None,
    )
    relevant = expected.intersection(retrieved_pages)
    return RetrievalCaseResult(
        id=case_id,
        expected_pages=expected_pages,
        retrieved_pages=retrieved_pages,
        first_relevant_rank=first_rank,
        page_hit=first_rank is not None,
        recall_at_k=len(relevant) / len(expected),
        precision_at_k=len(relevant) / max(len(retrieved_pages), 1),
        reciprocal_rank=0.0 if first_rank is None else 1 / first_rank,
        ndcg_at_k=0.0,
        latency_ms=1.0,
    )


def _retrieval_evaluation(
    mode: SearchMode,
    cases: list[RetrievalCaseResult],
) -> RetrievalEvaluation:
    """Create a classification-only retrieval evaluation.

    Parameters
    ----------
    mode : SearchMode
        Search strategy represented by the cases.
    cases : list[RetrievalCaseResult]
        Per-question ranking results.

    Returns
    -------
    RetrievalEvaluation
        Model containing only fields consumed by error analysis.
    """
    return RetrievalEvaluation(
        mode=mode,
        top_k=5,
        case_count=len(cases),
        page_hit_at_k=0.0,
        recall_at_k=0.0,
        precision_at_k=0.0,
        mrr=0.0,
        ndcg_at_k=0.0,
        mean_latency_ms=0.0,
        p95_latency_ms=0.0,
        cases=cases,
    )


def _quality_evaluation(cited_pages: dict[str, list[int]]) -> QualityEvaluation:
    """Create answer results containing the selected Citation pages.

    Parameters
    ----------
    cited_pages : dict[str, list[int]]
        Citation pages keyed by evaluation question identifier.

    Returns
    -------
    QualityEvaluation
        Classification-only quality model.
    """
    cases = [
        AnswerCaseResult(
            id=case_id,
            language="ko",
            intent="fact_lookup",
            answerable=True,
            abstained=False,
            passed=True,
            failure_reasons=[],
            citation_precision=1.0,
            citation_coverage=1.0,
            cited_pages=pages,
            page_match_accuracy=1.0,
            quote_match_rate=1.0,
            faithfulness=1.0,
            termination_correct=True,
            trajectory_correct=True,
            termination_reason=AgentTerminationReason.ANSWER_VALIDATED,
            search_modes=[SearchMode.RERANK],
            trace_events=[],
            retrieval_attempts=1,
            step_count=1,
            tool_error_count=0,
            latency_ms=0.0,
        )
        for case_id, pages in cited_pages.items()
    ]
    return QualityEvaluation(
        case_count=max(len(cases), 1),
        pass_rate=1.0,
        required_fact_coverage=1.0,
        numeric_accuracy=1.0,
        citation_precision=1.0,
        citation_coverage=1.0,
        page_match_accuracy=1.0,
        quote_match_rate=1.0,
        faithfulness=1.0,
        abstention_precision=1.0,
        abstention_recall=1.0,
        unsafe_answer_rate=0.0,
        false_abstention_rate=0.0,
        termination_accuracy=1.0,
        trajectory_accuracy=1.0,
        retry_success_rate=1.0,
        tool_error_recovery_rate=1.0,
        unnecessary_tool_call_rate=0.0,
        average_retrieval_attempts=1.0,
        average_tool_calls=1.0,
        average_steps=1.0,
        mean_latency_ms=0.0,
        max_step_violation_count=0,
        cases=cases,
    )


def test_error_analysis_classifies_actionable_failures() -> None:
    """Separate ranking misses, low ranks, wrong pages, and regressions."""
    rerank_cases = [
        _retrieval_case("Q1", [8], [9, 8, 10]),
        _retrieval_case("Q2", [3], [4, 5]),
        _retrieval_case("Q3", [6], [6, 7]),
    ]
    bm25_cases = [
        _retrieval_case("Q1", [8], [8, 9]),
        _retrieval_case("Q2", [3], [4, 5]),
        _retrieval_case("Q3", [6], [7, 6]),
    ]

    analysis = analyze_retrieval_failures(
        {
            SearchMode.RERANK: _retrieval_evaluation(
                SearchMode.RERANK,
                rerank_cases,
            ),
            SearchMode.BM25: _retrieval_evaluation(SearchMode.BM25, bm25_cases),
        },
        _quality_evaluation({"Q1": [9, 8], "Q2": [4], "Q3": [6]}),
    )

    by_id = {case.id: case for case in analysis.cases}
    assert by_id["Q1"].failure_types == [
        RetrievalFailureType.LOW_RANK,
        RetrievalFailureType.WRONG_PAGE,
        RetrievalFailureType.RERANK_REGRESSION,
    ]
    assert by_id["Q2"].failure_types == [
        RetrievalFailureType.MISSED,
        RetrievalFailureType.WRONG_PAGE,
    ]
    assert by_id["Q3"].failure_types == []
    assert analysis.failure_case_count == 2
    assert analysis.failure_counts == {
        RetrievalFailureType.LOW_RANK: 1,
        RetrievalFailureType.WRONG_PAGE: 2,
        RetrievalFailureType.RERANK_REGRESSION: 1,
        RetrievalFailureType.MISSED: 1,
    }


def test_error_analysis_requires_matching_quality_case() -> None:
    """Reject partial reports that cannot diagnose selected Citation pages."""
    retrieval = _retrieval_evaluation(
        SearchMode.RERANK,
        [_retrieval_case("Q1", [8], [8])],
    )

    with pytest.raises(ValueError, match="quality result is missing"):
        analyze_retrieval_failures(
            {SearchMode.RERANK: retrieval},
            _quality_evaluation({}),
        )
