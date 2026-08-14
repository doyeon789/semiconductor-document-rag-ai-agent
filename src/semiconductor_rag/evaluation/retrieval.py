"""Retrieval baseline datasets, metrics, and evaluation execution."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semiconductor_rag.agent import AgentTerminationReason
from semiconductor_rag.retrieval import SearchHit, SearchMode


class RetrievalCase(BaseModel):
    """Describe one query and its expected source evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    language: str = Field(default="ko", min_length=1)
    intent: str = Field(default="fact_lookup", min_length=1)
    expected_evidence_ids: list[str] = Field(default_factory=list)
    expected_pages: list[int] = Field(default_factory=list)
    answerable: bool = True
    required_facts: list[str] = Field(default_factory=list)
    required_numbers: list[str] = Field(default_factory=list)
    expected_search_modes: list[SearchMode] = Field(default_factory=list)
    expected_events: list[str] = Field(default_factory=list)
    expected_termination_reason: AgentTerminationReason | None = None

    @model_validator(mode="after")
    def validate_expected_evidence(self) -> RetrievalCase:
        """Keep answerability and gold-page annotations consistent.

        Returns
        -------
        RetrievalCase
            Validated evaluation case.

        Raises
        ------
        ValueError
            If answerable cases have no gold page or unanswerable cases do.
        """
        if self.answerable and not self.expected_pages:
            raise ValueError("answerable cases require expected_pages")
        if not self.answerable and self.expected_pages:
            raise ValueError("unanswerable cases must not define expected_pages")
        if len(set(self.expected_pages)) != len(self.expected_pages):
            raise ValueError("expected_pages must not contain duplicates")
        return self


class RetrievalDataset(BaseModel):
    """Describe a versioned retrieval evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    excluded_corpus_pages: list[int] = Field(default_factory=list)
    exclusion_reason: str | None = None
    cases: list[RetrievalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> RetrievalDataset:
        """Reject duplicate case identifiers within one dataset version.

        Returns
        -------
        RetrievalDataset
            Dataset with unique case identifiers.

        Raises
        ------
        ValueError
            If two cases share the same identifier.
        """
        case_ids = [case.id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case ids must be unique")
        return self


class RetrievalCaseResult(BaseModel):
    """Record the ranking outcome and latency for one query."""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected_pages: list[int]
    retrieved_pages: list[int]
    first_relevant_rank: int | None
    page_hit: bool
    recall_at_k: float = Field(ge=0.0, le=1.0)
    precision_at_k: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float
    ndcg_at_k: float = Field(ge=0.0, le=1.0)
    latency_ms: float


class RetrievalEvaluation(BaseModel):
    """Summarize one retrieval mode over an evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    mode: SearchMode
    top_k: int
    case_count: int
    page_hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
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
        recall_at_k=mean(result.recall_at_k for result in case_results),
        precision_at_k=mean(result.precision_at_k for result in case_results),
        mrr=mean(result.reciprocal_rank for result in case_results),
        ndcg_at_k=mean(result.ndcg_at_k for result in case_results),
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
    retrieved_relevant_pages = expected_pages.intersection(retrieved_pages)
    first_relevant_rank = next(
        (
            rank
            for rank, page_number in enumerate(retrieved_pages, start=1)
            if page_number in expected_pages
        ),
        None,
    )
    reciprocal_rank = 0.0 if first_relevant_rank is None else 1 / first_relevant_rank
    recall_at_k = len(retrieved_relevant_pages) / len(expected_pages)
    precision_at_k = (
        sum(page_number in expected_pages for page_number in retrieved_pages) / top_k
    )
    relevance = [int(page_number in expected_pages) for page_number in retrieved_pages]
    dcg = sum(
        relevant / math.log2(rank + 1)
        for rank, relevant in enumerate(relevance, start=1)
    )
    ideal_relevant_count = min(len(expected_pages), top_k)
    ideal_dcg = sum(
        1 / math.log2(rank + 1) for rank in range(1, ideal_relevant_count + 1)
    )
    return RetrievalCaseResult(
        id=case.id,
        expected_pages=case.expected_pages,
        retrieved_pages=retrieved_pages,
        first_relevant_rank=first_relevant_rank,
        page_hit=first_relevant_rank is not None,
        recall_at_k=recall_at_k,
        precision_at_k=precision_at_k,
        reciprocal_rank=reciprocal_rank,
        ndcg_at_k=0.0 if ideal_dcg == 0 else dcg / ideal_dcg,
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
