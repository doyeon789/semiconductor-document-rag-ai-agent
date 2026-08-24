"""Unit tests for retrieval dataset loading and baseline metrics."""

import math
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from semiconductor_rag.domain import Chunk, ChunkType, DocumentSource
from semiconductor_rag.evaluation import (
    GoldEvidence,
    RetrievalCase,
    RetrievalDataset,
    evaluate_retrieval,
    load_retrieval_dataset,
)
from semiconductor_rag.retrieval import SearchHit, SearchMode

VERSION_ID = UUID("99999999-9999-4999-8999-999999999999")


def _make_hit(
    number: int,
    page: int,
    document_id: str | None = None,
) -> SearchHit:
    """Create a stable page-aware hit for metric tests.

    Parameters
    ----------
    number : int
        Integer used to construct a stable chunk identifier.
    page : int
        One-based source page number.
    document_id : str or None, default=None
        Optional source identifier for multi-document metric tests.

    Returns
    -------
    SearchHit
        Ranked test hit.
    """
    text = f"page {page}"
    source = (
        None
        if document_id is None
        else DocumentSource(
            document_id=document_id,
            title=f"Document {document_id}",
            publisher="Test Publisher",
            language="en-US",
            version="test-v1",
        )
    )
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
        source=source,
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


class ScriptedEvaluationService:
    """Return caller-supplied rankings for multi-document metric tests."""

    def __init__(self, rankings: dict[str, tuple[SearchHit, ...]]) -> None:
        """Store deterministic rankings by evaluation query.

        Parameters
        ----------
        rankings : dict[str, tuple[SearchHit, ...]]
            Ranked hits keyed by query text.
        """
        self._rankings = rankings
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
        """Return one stored ranking truncated to the requested limit.

        Parameters
        ----------
        query : str
            Key selecting one stored ranking.
        mode : SearchMode, default=SearchMode.HYBRID
            Ignored retrieval strategy.
        top_k : int, default=5
            Maximum result count.

        Returns
        -------
        tuple[SearchHit, ...]
            Stored deterministic ranking.
        """
        return self._rankings[query][:top_k]


def test_load_retrieval_dataset_preserves_leakage_exclusion() -> None:
    """Load all PDF-authored questions and exclude their source page."""
    dataset_path = Path("data/evaluation/retrieval_cases.json")

    dataset = load_retrieval_dataset(dataset_path)

    assert len(dataset.cases) == 12
    assert dataset.schema_version == 1
    assert dataset.document_id == "SEMI-8P-RAG-KO"
    assert dataset.excluded_corpus_pages == [65]


def test_schema_version_two_accepts_declared_multi_document_gold() -> None:
    """Validate corpus metadata while retaining legacy dataset fields."""
    dataset = RetrievalDataset.model_validate(
        {
            "schema_version": 2,
            "dataset_id": "ai-security-development-v1",
            "corpus_id": "ai-security-guides-v1",
            "split": "development",
            "document_ids": ["nist", "owasp"],
            "cases": [
                {
                    "id": "Q1",
                    "query": "How should prompt injection be mitigated?",
                    "language": "en",
                    "gold": [
                        {"document_id": "owasp", "pages": [20, 21]},
                    ],
                }
            ],
        }
    )

    assert dataset.document_id == ""
    assert dataset.document_version == ""
    assert dataset.cases[0].gold == [GoldEvidence(document_id="owasp", pages=[20, 21])]


def test_schema_version_two_rejects_undeclared_gold_document() -> None:
    """Reject gold evidence that cannot belong to the declared corpus slice."""
    with pytest.raises(ValidationError, match="not declared: owasp"):
        RetrievalDataset.model_validate(
            {
                "schema_version": 2,
                "dataset_id": "ai-security-development-v1",
                "corpus_id": "ai-security-guides-v1",
                "split": "development",
                "document_ids": ["nist"],
                "cases": [
                    {
                        "id": "Q1",
                        "query": "prompt injection",
                        "gold": [{"document_id": "owasp", "pages": [20]}],
                    }
                ],
            }
        )


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
    assert result.recall_at_k == pytest.approx(2 / 3)
    assert result.precision_at_k == pytest.approx(1 / 3)
    assert result.mrr == pytest.approx(0.5)
    assert result.ndcg_at_k == pytest.approx((1 + 1 / math.log2(3)) / 3)
    assert result.case_count == 3
    assert result.p95_latency_ms >= result.mean_latency_ms


def test_evaluate_retrieval_accepts_reranked_mode() -> None:
    """Record reranked retrieval as a separately comparable evaluation run."""
    service = EvaluationTestService()
    cases = [
        RetrievalCase(
            id="Q1",
            query="first",
            expected_evidence_ids=["A"],
            expected_pages=[3],
        )
    ]

    result = evaluate_retrieval(service, cases, SearchMode.RERANK, top_k=2)

    assert service.prepared_mode is SearchMode.RERANK
    assert result.mode is SearchMode.RERANK
    assert result.page_hit_at_k == 1.0


def test_multi_document_evaluation_matches_document_and_page_key() -> None:
    """Reject a same-numbered page from the wrong source document."""
    service = ScriptedEvaluationService(
        {
            "same-page": (
                _make_hit(1, 3, "wrong-document"),
                _make_hit(2, 4, "expected-document"),
            )
        }
    )
    case = RetrievalCase(
        id="Q1",
        query="same-page",
        gold=[GoldEvidence(document_id="expected-document", pages=[3])],
    )

    result = evaluate_retrieval(service, [case], SearchMode.BM25, top_k=2)

    assert result.page_hit_at_k == 0.0
    assert result.mrr == 0.0
    assert result.document_coverage_at_k == 1.0
    assert result.cases[0].retrieved_pages == [3, 4]
    assert result.cases[0].retrieved_document_ids == [
        "wrong-document",
        "expected-document",
    ]


def test_multi_document_evaluation_deduplicates_document_page_hits() -> None:
    """Count repeated chunks from one physical page as one ranked result."""
    service = ScriptedEvaluationService(
        {
            "duplicates": (
                _make_hit(1, 3, "nist"),
                _make_hit(2, 3, "nist"),
                _make_hit(3, 7, "owasp"),
            )
        }
    )
    case = RetrievalCase(
        id="Q1",
        query="duplicates",
        gold=[
            GoldEvidence(document_id="nist", pages=[3]),
            GoldEvidence(document_id="owasp", pages=[7]),
        ],
    )

    result = evaluate_retrieval(service, [case], SearchMode.BM25, top_k=3)

    assert result.page_hit_at_k == 1.0
    assert result.recall_at_k == 1.0
    assert result.precision_at_k == pytest.approx(2 / 3)
    assert result.mrr == 1.0
    assert result.ndcg_at_k == 1.0
    assert result.document_coverage_at_k == 1.0
    assert result.cases[0].retrieved_pages == [3, 7]


def test_multi_document_evaluation_reports_partial_document_coverage() -> None:
    """Measure how many required source documents appear in the ranking."""
    service = ScriptedEvaluationService(
        {
            "comparison": (
                _make_hit(1, 3, "nist"),
                _make_hit(2, 9, "kisa"),
            )
        }
    )
    case = RetrievalCase(
        id="Q1",
        query="comparison",
        gold=[
            GoldEvidence(document_id="nist", pages=[3]),
            GoldEvidence(document_id="owasp", pages=[7]),
        ],
    )

    result = evaluate_retrieval(service, [case], SearchMode.BM25, top_k=2)

    assert result.document_coverage_at_k == 0.5
    assert result.cases[0].document_coverage_at_k == 0.5
    assert result.recall_at_k == 0.5


def test_multi_document_evaluation_requires_hit_source_metadata() -> None:
    """Fail instead of silently matching page numbers without document IDs."""
    service = ScriptedEvaluationService({"missing-source": (_make_hit(1, 3),)})
    case = RetrievalCase(
        id="Q1",
        query="missing-source",
        gold=[GoldEvidence(document_id="nist", pages=[3])],
    )

    with pytest.raises(ValueError, match="require source metadata"):
        evaluate_retrieval(service, [case], SearchMode.BM25)


def test_evaluate_retrieval_rejects_unanswerable_cases() -> None:
    """Keep negative cases out of positive-gold ranking aggregates."""
    service = ScriptedEvaluationService({"missing": ()})
    case = RetrievalCase(
        id="Q1",
        query="missing",
        answerable=False,
    )

    with pytest.raises(ValueError, match="requires answerable cases: Q1"):
        evaluate_retrieval(service, [case], SearchMode.BM25)


def test_retrieval_case_rejects_inconsistent_answerability() -> None:
    """Require gold pages only for questions the corpus can answer."""
    with pytest.raises(ValidationError, match="answerable cases require"):
        RetrievalCase(id="Q1", query="missing", answerable=True)

    with pytest.raises(ValidationError, match="must not define"):
        RetrievalCase(
            id="Q2",
            query="not answerable",
            answerable=False,
            expected_pages=[3],
        )
