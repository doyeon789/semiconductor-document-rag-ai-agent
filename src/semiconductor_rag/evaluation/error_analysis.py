"""Classify retrieval and Evidence selection failures by evaluation case."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.evaluation.quality import QualityEvaluation
from semiconductor_rag.evaluation.retrieval import (
    RetrievalCaseResult,
    RetrievalEvaluation,
)
from semiconductor_rag.retrieval import SearchMode


class RetrievalFailureType(StrEnum):
    """Describe one actionable retrieval or Evidence selection failure."""

    MISSED = "missed"
    LOW_RANK = "low_rank"
    WRONG_PAGE = "wrong_page"
    RERANK_REGRESSION = "rerank_regression"


class RetrievalFailureCase(BaseModel):
    """Record the failure categories and source pages for one question."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    expected_pages: list[int]
    retrieved_pages: list[int]
    cited_pages: list[int]
    first_relevant_rank: int | None
    failure_types: list[RetrievalFailureType]


class RetrievalErrorAnalysis(BaseModel):
    """Aggregate failure categories for one preferred retrieval strategy."""

    model_config = ConfigDict(extra="forbid")

    preferred_mode: SearchMode
    case_count: int = Field(ge=1)
    failure_case_count: int = Field(ge=0)
    failure_counts: dict[RetrievalFailureType, int]
    cases: list[RetrievalFailureCase]


def analyze_retrieval_failures(
    retrieval: Mapping[SearchMode, RetrievalEvaluation],
    quality: QualityEvaluation,
    preferred_mode: SearchMode = SearchMode.RERANK,
    low_rank_threshold: int = 1,
) -> RetrievalErrorAnalysis:
    """Classify missed, low-ranked, wrong-page, and rerank failures.

    Parameters
    ----------
    retrieval : collections.abc.Mapping[SearchMode, RetrievalEvaluation]
        Per-mode retrieval results from one evaluation run.
    quality : QualityEvaluation
        Answer results containing the pages selected as Citations.
    preferred_mode : SearchMode, default=SearchMode.RERANK
        Retrieval strategy treated as the final ranking.
    low_rank_threshold : int, default=1
        Largest first-relevant rank considered immediately usable.

    Returns
    -------
    RetrievalErrorAnalysis
        Per-case failure types and aggregate counts.

    Raises
    ------
    ValueError
        If the preferred mode is absent, the threshold is invalid, or case
        identifiers do not match the quality results.
    """
    if preferred_mode not in retrieval:
        raise ValueError(f"preferred retrieval mode is missing: {preferred_mode.value}")
    if low_rank_threshold < 1:
        raise ValueError("low_rank_threshold must be positive")

    preferred = retrieval[preferred_mode]
    quality_by_id = {case.id: case for case in quality.cases if case.answerable}
    baseline_by_mode = {
        mode: {case.id: case for case in evaluation.cases}
        for mode, evaluation in retrieval.items()
        if mode is not preferred_mode
    }
    failures: list[RetrievalFailureCase] = []
    counts: Counter[RetrievalFailureType] = Counter()
    for result in preferred.cases:
        answer = quality_by_id.get(result.id)
        if answer is None:
            raise ValueError(
                f"quality result is missing for retrieval case: {result.id}"
            )
        failure_types = _classify_case(
            result,
            answer.cited_pages,
            baseline_by_mode,
            low_rank_threshold,
        )
        counts.update(failure_types)
        failures.append(
            RetrievalFailureCase(
                id=result.id,
                expected_pages=result.expected_pages,
                retrieved_pages=result.retrieved_pages,
                cited_pages=answer.cited_pages,
                first_relevant_rank=result.first_relevant_rank,
                failure_types=failure_types,
            )
        )
    return RetrievalErrorAnalysis(
        preferred_mode=preferred_mode,
        case_count=len(failures),
        failure_case_count=sum(bool(case.failure_types) for case in failures),
        failure_counts={failure_type: counts[failure_type] for failure_type in counts},
        cases=failures,
    )


def _classify_case(
    preferred: RetrievalCaseResult,
    cited_pages: list[int],
    baselines: Mapping[SearchMode, Mapping[str, RetrievalCaseResult]],
    low_rank_threshold: int,
) -> list[RetrievalFailureType]:
    """Return deterministic failure categories for one preferred ranking."""
    failure_types: list[RetrievalFailureType] = []
    if not preferred.page_hit:
        failure_types.append(RetrievalFailureType.MISSED)
    elif (
        preferred.first_relevant_rank is not None
        and preferred.first_relevant_rank > low_rank_threshold
    ):
        failure_types.append(RetrievalFailureType.LOW_RANK)
    if set(cited_pages).difference(preferred.expected_pages):
        failure_types.append(RetrievalFailureType.WRONG_PAGE)
    if _rerank_regressed(preferred, baselines):
        failure_types.append(RetrievalFailureType.RERANK_REGRESSION)
    return failure_types


def _rerank_regressed(
    preferred: RetrievalCaseResult,
    baselines: Mapping[SearchMode, Mapping[str, RetrievalCaseResult]],
) -> bool:
    """Return whether any first-stage ranking placed gold evidence higher."""
    baseline_ranks = [
        result.first_relevant_rank
        for cases in baselines.values()
        if (result := cases.get(preferred.id)) is not None
        and result.first_relevant_rank is not None
    ]
    if not baseline_ranks:
        return False
    return preferred.first_relevant_rank is None or preferred.first_relevant_rank > min(
        baseline_ranks
    )
