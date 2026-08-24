"""Retrieval baseline datasets, metrics, and evaluation execution."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semiconductor_rag.agent import AgentTerminationReason
from semiconductor_rag.retrieval import SearchHit, SearchMode


class GoldEvidence(BaseModel):
    """Group expected physical PDF pages under one source document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    pages: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pages(self) -> GoldEvidence:
        """Reject duplicate physical pages within one source document.

        Returns
        -------
        GoldEvidence
            Gold evidence with unique one-based pages.

        Raises
        ------
        ValueError
            If the same physical page is listed more than once.
        """
        if len(set(self.pages)) != len(self.pages):
            raise ValueError("gold evidence pages must not contain duplicates")
        return self


class RetrievalCase(BaseModel):
    """Describe one query and its expected source evidence."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    language: str = Field(default="ko", min_length=1)
    intent: str = Field(default="fact_lookup", min_length=1)
    expected_evidence_ids: list[str] = Field(default_factory=list)
    expected_pages: list[int] = Field(default_factory=list)
    gold: list[GoldEvidence] = Field(default_factory=list)
    answerable: bool = True
    required_facts: list[str] = Field(default_factory=list)
    required_numbers: list[str] = Field(default_factory=list)
    expected_search_modes: list[SearchMode] = Field(default_factory=list)
    expected_events: list[str] = Field(default_factory=list)
    expected_termination_reason: AgentTerminationReason | None = None

    @model_validator(mode="after")
    def validate_expected_evidence(self) -> RetrievalCase:
        """Keep answerability and gold evidence annotations consistent.

        Returns
        -------
        RetrievalCase
            Validated evaluation case.

        Raises
        ------
        ValueError
            If answerable cases have no gold evidence, both legacy and
            multi-document gold are defined, or unanswerable cases define
            gold evidence.
        """
        if self.expected_pages and self.gold:
            raise ValueError("cases must not define both expected_pages and gold")
        if self.answerable and not (self.expected_pages or self.gold):
            raise ValueError("answerable cases require expected_pages or gold")
        if not self.answerable and (self.expected_pages or self.gold):
            raise ValueError("unanswerable cases must not define gold evidence")
        if len(set(self.expected_pages)) != len(self.expected_pages):
            raise ValueError("expected_pages must not contain duplicates")
        gold_document_ids = [evidence.document_id for evidence in self.gold]
        if len(set(gold_document_ids)) != len(gold_document_ids):
            raise ValueError("gold document ids must be unique within a case")
        return self


class RetrievalDataset(BaseModel):
    """Describe a versioned retrieval evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
    dataset_id: str = Field(min_length=1)
    document_id: str = ""
    document_version: str = ""
    corpus_id: str | None = Field(default=None, min_length=1)
    split: Literal["development", "holdout"] | None = None
    document_ids: list[Annotated[str, Field(min_length=1)]] = Field(
        default_factory=list
    )
    excluded_corpus_pages: list[int] = Field(default_factory=list)
    exclusion_reason: str | None = None
    cases: list[RetrievalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> RetrievalDataset:
        """Validate identifiers and the selected dataset schema contract.

        Returns
        -------
        RetrievalDataset
            Dataset with unique case and document identifiers.

        Raises
        ------
        ValueError
            If identifiers are duplicated, schema-specific metadata is
            missing, or a gold document is outside the declared corpus.
        """
        case_ids = [case.id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case ids must be unique")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("evaluation document ids must be unique")

        if self.schema_version == 1:
            if not self.document_id.strip() or not self.document_version.strip():
                raise ValueError(
                    "schema version 1 requires document_id and document_version"
                )
            if (
                self.corpus_id is not None
                or self.split is not None
                or self.document_ids
            ):
                raise ValueError(
                    "corpus_id, split, and document_ids require schema version 2"
                )
            if any(case.gold for case in self.cases):
                raise ValueError("multi-document gold requires schema version 2")
            return self

        if self.corpus_id is None or self.split is None or not self.document_ids:
            raise ValueError(
                "schema version 2 requires corpus_id, split, and document_ids"
            )
        if bool(self.document_id.strip()) != bool(self.document_version.strip()):
            raise ValueError(
                "legacy document_id and document_version must be defined together"
            )
        answerable_without_gold = [
            case.id for case in self.cases if case.answerable and not case.gold
        ]
        if answerable_without_gold:
            raise ValueError("schema version 2 answerable cases require gold")
        declared_document_ids = set(self.document_ids)
        unknown_document_ids = {
            evidence.document_id
            for case in self.cases
            for evidence in case.gold
            if evidence.document_id not in declared_document_ids
        }
        if unknown_document_ids:
            unknown = ", ".join(sorted(unknown_document_ids))
            raise ValueError(f"gold document ids are not declared: {unknown}")
        return self


class RetrievalCaseResult(BaseModel):
    """Record the ranking outcome and latency for one query."""

    model_config = ConfigDict(extra="forbid")

    id: str
    gold: list[GoldEvidence] = Field(default_factory=list)
    expected_pages: list[int]
    retrieved_pages: list[int]
    retrieved_document_ids: list[str] = Field(default_factory=list)
    first_relevant_rank: int | None
    page_hit: bool
    document_coverage_at_k: float = Field(default=0.0, ge=0.0, le=1.0)
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
    document_coverage_at_k: float = Field(default=0.0, ge=0.0, le=1.0)
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
        If no cases are provided, ``top_k`` is not positive, or any case is
        unanswerable. Retrieval ranking metrics require positive gold evidence;
        callers must evaluate abstention cases separately.
    """
    if not cases:
        raise ValueError("cases must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    unanswerable_case_ids = [case.id for case in cases if not case.answerable]
    if unanswerable_case_ids:
        case_ids = ", ".join(unanswerable_case_ids)
        raise ValueError(f"retrieval evaluation requires answerable cases: {case_ids}")

    search_service.prepare(mode)
    case_results = [_evaluate_case(search_service, case, mode, top_k) for case in cases]
    latencies = [result.latency_ms for result in case_results]
    return RetrievalEvaluation(
        mode=mode,
        top_k=top_k,
        case_count=len(case_results),
        page_hit_at_k=mean(float(result.page_hit) for result in case_results),
        document_coverage_at_k=mean(
            result.document_coverage_at_k for result in case_results
        ),
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
    if case.gold:
        unique_hits = _deduplicate_multi_document_hits(hits)
        expected_evidence = {
            (evidence.document_id, page)
            for evidence in case.gold
            for page in evidence.pages
        }
        retrieved_evidence = [
            (hit.source.document_id, hit.chunk.page_start)
            for hit in unique_hits
            if hit.source is not None
        ]
        relevance = [
            int(evidence_key in expected_evidence)
            for evidence_key in retrieved_evidence
        ]
        expected_count = len(expected_evidence)
        retrieved_relevant_count = len(
            expected_evidence.intersection(retrieved_evidence)
        )
        expected_document_ids = {evidence.document_id for evidence in case.gold}
        retrieved_document_ids = [
            hit.source.document_id for hit in unique_hits if hit.source is not None
        ]
        document_coverage_at_k = len(
            expected_document_ids.intersection(retrieved_document_ids)
        ) / len(expected_document_ids)
        expected_pages = [page for evidence in case.gold for page in evidence.pages]
    else:
        unique_hits = _deduplicate_legacy_hits(hits)
        expected_page_set = set(case.expected_pages)
        retrieved_pages = [hit.chunk.page_start for hit in unique_hits]
        relevance = [int(page in expected_page_set) for page in retrieved_pages]
        expected_count = len(expected_page_set)
        retrieved_relevant_count = len(expected_page_set.intersection(retrieved_pages))
        retrieved_document_ids = []
        document_coverage_at_k = float(bool(unique_hits))
        expected_pages = case.expected_pages

    retrieved_pages = [hit.chunk.page_start for hit in unique_hits]
    first_relevant_rank = next(
        (rank for rank, relevant in enumerate(relevance, start=1) if relevant),
        None,
    )
    reciprocal_rank = 0.0 if first_relevant_rank is None else 1 / first_relevant_rank
    recall_at_k = retrieved_relevant_count / expected_count
    precision_at_k = sum(relevance) / top_k
    dcg = sum(
        relevant / math.log2(rank + 1)
        for rank, relevant in enumerate(relevance, start=1)
    )
    ideal_relevant_count = min(expected_count, top_k)
    ideal_dcg = sum(
        1 / math.log2(rank + 1) for rank in range(1, ideal_relevant_count + 1)
    )
    return RetrievalCaseResult(
        id=case.id,
        gold=case.gold,
        expected_pages=expected_pages,
        retrieved_pages=retrieved_pages,
        retrieved_document_ids=retrieved_document_ids,
        first_relevant_rank=first_relevant_rank,
        page_hit=first_relevant_rank is not None,
        document_coverage_at_k=document_coverage_at_k,
        recall_at_k=recall_at_k,
        precision_at_k=precision_at_k,
        reciprocal_rank=reciprocal_rank,
        ndcg_at_k=0.0 if ideal_dcg == 0 else dcg / ideal_dcg,
        latency_ms=latency_ms,
    )


def _deduplicate_multi_document_hits(
    hits: tuple[SearchHit, ...],
) -> tuple[SearchHit, ...]:
    """Keep the first ranked hit for each document and physical page.

    Parameters
    ----------
    hits : tuple of SearchHit
        Ranked multi-document search hits.

    Returns
    -------
    tuple of SearchHit
        Ranking with duplicate document-page keys removed.

    Raises
    ------
    ValueError
        If any hit lacks source metadata required for an unambiguous key.
    """
    missing_source = next((hit for hit in hits if hit.source is None), None)
    if missing_source is not None:
        raise ValueError("multi-document retrieval hits require source metadata")

    seen: set[tuple[str, int]] = set()
    unique_hits: list[SearchHit] = []
    for hit in hits:
        if hit.source is None:
            continue
        key = (hit.source.document_id, hit.chunk.page_start)
        if key in seen:
            continue
        seen.add(key)
        unique_hits.append(hit)
    return tuple(unique_hits)


def _deduplicate_legacy_hits(
    hits: tuple[SearchHit, ...],
) -> tuple[SearchHit, ...]:
    """Keep the first ranked hit for each legacy single-document page.

    Parameters
    ----------
    hits : tuple of SearchHit
        Ranked hits from a single-document evaluation.

    Returns
    -------
    tuple of SearchHit
        Ranking with duplicate physical pages removed.
    """
    seen_pages: set[int] = set()
    unique_hits: list[SearchHit] = []
    for hit in hits:
        page_number = hit.chunk.page_start
        if page_number in seen_pages:
            continue
        seen_pages.add(page_number)
        unique_hits.append(hit)
    return tuple(unique_hits)


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
