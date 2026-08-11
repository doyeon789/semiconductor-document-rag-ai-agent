"""Unit tests for retrieval dataset loading and baseline metrics."""

from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.evaluation import (
    RetrievalCase,
    evaluate_retrieval,
    load_retrieval_dataset,
)
from semiconductor_rag.retrieval import SearchHit, SearchMode

VERSION_ID = UUID("99999999-9999-4999-8999-999999999999")


def _make_hit(number: int, page: int) -> SearchHit:
    """Create a stable page-aware hit for metric tests.

    Parameters
    ----------
    number : int
        Integer used to construct a stable chunk identifier.
    page : int
        One-based source page number.

    Returns
    -------
    SearchHit
        Ranked test hit.
    """
    text = f"page {page}"
    return SearchHit(
        chunk=Chunk(
            chunk_id=UUID(int=number),
            version_id=VERSION_ID,
            chunk_type=ChunkType.TEXT,
            text=text,
            page_start=page,
            page_end=page,
            token_count=2,
            content_hash=sha256(text.encode()).hexdigest(),
        ),
        score=1 / number,
    )


class EvaluationTestService:
    """Return deterministic results for evaluation metric tests."""

    def __init__(self) -> None:
        """Create an unprepared test service."""
        self.prepared_mode: SearchMode | None = None

    def prepare(self, mode: SearchMode) -> None:
        """Record the retrieval mode prepared by the evaluator.

        Parameters
        ----------
        mode : SearchMode
            Retrieval strategy selected for the run.
        """
        self.prepared_mode = mode

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.HYBRID,
        top_k: int = 5,
    ) -> tuple[SearchHit, ...]:
        """Return one relevant result at a deterministic rank.

        Parameters
        ----------
        query : str
            Query identifier used to select a ranking.
        mode : SearchMode, default=SearchMode.HYBRID
            Ignored selected strategy.
        top_k : int, default=5
            Maximum result count.

        Returns
        -------
        tuple[SearchHit, ...]
            Fixed ranked results.
        """
        rankings = {
            "first": (_make_hit(1, 3), _make_hit(2, 9)),
            "second": (_make_hit(1, 9), _make_hit(2, 3)),
            "miss": (_make_hit(1, 9),),
        }
        return rankings[query][:top_k]


def test_load_retrieval_dataset_preserves_leakage_exclusion() -> None:
    """Load all PDF-authored questions and exclude their source page."""
    dataset_path = Path("data/evaluation/retrieval_cases.json")

    dataset = load_retrieval_dataset(dataset_path)

    assert len(dataset.cases) == 12
    assert dataset.excluded_corpus_pages == [65]


def test_evaluate_retrieval_calculates_page_hit_and_mrr() -> None:
    """Aggregate hit rate and first-relevant reciprocal rank."""
    service = EvaluationTestService()
    cases = [
        RetrievalCase(
            id="Q1",
            query="first",
            expected_evidence_ids=["A"],
            expected_pages=[3],
        ),
        RetrievalCase(
            id="Q2",
            query="second",
            expected_evidence_ids=["A"],
            expected_pages=[3],
        ),
        RetrievalCase(
            id="Q3",
            query="miss",
            expected_evidence_ids=["A"],
            expected_pages=[3],
        ),
    ]

    result = evaluate_retrieval(service, cases, SearchMode.BM25, top_k=2)

    assert service.prepared_mode is SearchMode.BM25
    assert result.page_hit_at_k == pytest.approx(2 / 3)
    assert result.mrr == pytest.approx(0.5)
    assert result.case_count == 3
    assert result.p95_latency_ms >= result.mean_latency_ms
