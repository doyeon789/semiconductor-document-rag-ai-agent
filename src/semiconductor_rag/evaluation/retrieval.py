"""Retrieval baseline datasets, metrics, and evaluation execution."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.retrieval import SearchHit, SearchMode


class RetrievalCase(BaseModel):
    """Describe one query and its expected source evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_evidence_ids: list[str] = Field(min_length=1)
    expected_pages: list[int] = Field(min_length=1)


class RetrievalDataset(BaseModel):
    """Describe a versioned retrieval evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    excluded_corpus_pages: list[int] = Field(default_factory=list)
    exclusion_reason: str | None = None
    cases: list[RetrievalCase] = Field(min_length=1)


class RetrievalCaseResult(BaseModel):
    """Record the ranking outcome and latency for one query."""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected_pages: list[int]
    retrieved_pages: list[int]
    first_relevant_rank: int | None
    page_hit: bool
    reciprocal_rank: float
    latency_ms: float


class RetrievalEvaluation(BaseModel):
    """Summarize one retrieval mode over an evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    mode: SearchMode
    top_k: int
    case_count: int
    page_hit_at_k: float
    mrr: float
    mean_latency_ms: float
    p95_latency_ms: float
    cases: list[RetrievalCaseResult]


class EvaluationSearchService(Protocol):
    """Define the search behavior needed by retrieval evaluation."""

    def prepare(self, mode: SearchMode) -> None:
        """Prepare one retrieval mode outside measured query latency.

        Parameters
        ----------
        mode : SearchMode
            Retrieval strategy that will be evaluated.
        """
        ...

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.HYBRID,
        top_k: int = 5,
    ) -> tuple[SearchHit, ...]:
        """Search the evaluation corpus.

        Parameters
        ----------
        query : str
            Evaluation query.
        mode : SearchMode, default=SearchMode.HYBRID
            Retrieval strategy.
        top_k : int, default=5
            Maximum result count.

        Returns
        -------
        tuple[SearchHit, ...]
            Ranked page-traceable hits.
        """
        ...


def load_retrieval_dataset(path: str | Path) -> RetrievalDataset:
    """Load and validate a retrieval dataset from JSON.

    Parameters
    ----------
    path : str or pathlib.Path
        JSON dataset path.

    Returns
    -------
    RetrievalDataset
        Validated versioned evaluation cases.
    """
    return RetrievalDataset.model_validate_json(Path(path).read_text(encoding="utf-8"))


def evaluate_retrieval(
    search_service: EvaluationSearchService,
    cases: list[RetrievalCase],
    mode: SearchMode,
    top_k: int = 5,
) -> RetrievalEvaluation:
    """Measure page hit rate, MRR, and query latency for one search mode.

    Index construction and model loading happen through ``prepare`` before the
    timed query loop.

    Parameters
    ----------
    search_service : EvaluationSearchService
        Prepared local corpus search service.
    cases : list[RetrievalCase]
        Evaluation questions and expected pages.
    mode : SearchMode
        Retrieval strategy to measure.
    top_k : int, default=5
        Number of ranked chunks inspected per query.

    Returns
    -------
    RetrievalEvaluation
        Per-query results and aggregate baseline metrics.

    Raises
    ------
    ValueError
        If no cases are provided or ``top_k`` is not positive.
    """
    if not cases:
        raise ValueError("cases must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be positive")

    search_service.prepare(mode)
    case_results = [_evaluate_case(search_service, case, mode, top_k) for case in cases]
    latencies = [result.latency_ms for result in case_results]
    return RetrievalEvaluation(
        mode=mode,
        top_k=top_k,
        case_count=len(case_results),
        page_hit_at_k=mean(float(result.page_hit) for result in case_results),
        mrr=mean(result.reciprocal_rank for result in case_results),
        mean_latency_ms=mean(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        cases=case_results,
    )


def _evaluate_case(
    search_service: EvaluationSearchService,
    case: RetrievalCase,
    mode: SearchMode,
    top_k: int,
) -> RetrievalCaseResult:
    """Measure and score one retrieval query.

    Parameters
    ----------
    search_service : EvaluationSearchService
        Local corpus search service.
    case : RetrievalCase
        Query and expected source pages.
    mode : SearchMode
        Retrieval strategy to measure.
    top_k : int
        Maximum ranked result count.

    Returns
    -------
    RetrievalCaseResult
        Retrieved pages, first relevant rank, and measured latency.
    """
    started_at = perf_counter()
    hits = search_service.search(case.query, mode, top_k)
    latency_ms = (perf_counter() - started_at) * 1_000
    retrieved_pages = [hit.chunk.page_start for hit in hits]
    expected_pages = set(case.expected_pages)
    first_relevant_rank = next(
        (
            rank
            for rank, page_number in enumerate(retrieved_pages, start=1)
            if page_number in expected_pages
        ),
        None,
    )
    reciprocal_rank = 0.0 if first_relevant_rank is None else 1 / first_relevant_rank
    return RetrievalCaseResult(
        id=case.id,
        expected_pages=case.expected_pages,
        retrieved_pages=retrieved_pages,
        first_relevant_rank=first_relevant_rank,
        page_hit=first_relevant_rank is not None,
        reciprocal_rank=reciprocal_rank,
        latency_ms=latency_ms,
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Return a nearest-rank percentile from a non-empty sample.

    Parameters
    ----------
    values : list[float]
        Numeric samples.
    percentile : float
        Requested percentile in the inclusive range from zero to one.

    Returns
    -------
    float
        Nearest-rank percentile value.

    Raises
    ------
    ValueError
        If the sample is empty or the percentile is outside zero to one.
    """
    if not values:
        raise ValueError("values must not be empty")
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be between zero and one")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]
