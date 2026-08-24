"""Unit tests for the multi-document retrieval evaluation CLI helpers."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from scripts.evaluate_retrieval import (
    _summarize_corpus,
    validate_dataset_against_corpus,
)
from semiconductor_rag.corpus import CorpusDocument, LoadedCorpus
from semiconductor_rag.domain import Chunk, ChunkType, DocumentSource
from semiconductor_rag.evaluation import RetrievalDataset, load_retrieval_dataset

VERSION_ID = UUID("88888888-8888-4888-8888-888888888888")


def _document(
    document_id: str = "guide",
    page_count: int = 4,
    excluded_pages: tuple[int, ...] = (2,),
    searchable_pages: tuple[int, ...] = (1, 3, 4),
) -> CorpusDocument:
    """Create one deterministic corpus document for annotation validation.

    Parameters
    ----------
    document_id : str, default="guide"
        Stable document identifier.
    page_count : int, default=4
        Physical PDF page count.
    excluded_pages : tuple of int, default=(2,)
        Pages intentionally absent from search.
    searchable_pages : tuple of int, default=(1, 3, 4)
        Pages represented by at least one chunk.

    Returns
    -------
    CorpusDocument
        In-memory verified document fixture.
    """
    chunks = tuple(
        _chunk(page_number, offset)
        for offset, page_number in enumerate(searchable_pages, 1)
    )
    return CorpusDocument(
        source=DocumentSource(
            document_id=document_id,
            title="Test Guide",
            publisher="Test Publisher",
            language="en-US",
            version="test-v1",
        ),
        version_id=VERSION_ID,
        pdf_path=Path("test.pdf"),
        page_count=page_count,
        excluded_pages=excluded_pages,
        chunks=chunks,
    )


def _chunk(page_number: int, offset: int) -> Chunk:
    """Create one searchable page chunk.

    Parameters
    ----------
    page_number : int
        One-based physical PDF page.
    offset : int
        Positive value used to keep identifiers unique.

    Returns
    -------
    Chunk
        Page-local text chunk fixture.
    """
    text = f"searchable page {page_number}"
    return Chunk(
        chunk_id=UUID(int=offset),
        version_id=VERSION_ID,
        chunk_type=ChunkType.TEXT,
        text=text,
        page_start=page_number,
        page_end=page_number,
        token_count=3,
        content_hash=sha256(text.encode()).hexdigest(),
    )


def _dataset(page_number: int = 3, corpus_id: str = "test-corpus") -> RetrievalDataset:
    """Create one schema-v2 dataset targeting a physical page.

    Parameters
    ----------
    page_number : int, default=3
        Gold physical page.
    corpus_id : str, default="test-corpus"
        Corpus identifier recorded by the dataset.

    Returns
    -------
    RetrievalDataset
        Valid multi-document retrieval dataset fixture.
    """
    return RetrievalDataset.model_validate(
        {
            "schema_version": 2,
            "dataset_id": "test-development-v1",
            "corpus_id": corpus_id,
            "split": "development",
            "document_ids": ["guide"],
            "cases": [
                {
                    "id": "Q1",
                    "query": "Where is the evidence?",
                    "gold": [{"document_id": "guide", "pages": [page_number]}],
                }
            ],
        }
    )


def test_committed_ai_security_datasets_keep_frozen_splits() -> None:
    """Keep the development and holdout contracts balanced and disjoint."""
    development = load_retrieval_dataset(
        "data/evaluation/ai_security_retrieval_dev.json"
    )
    holdout = load_retrieval_dataset(
        "data/evaluation/ai_security_retrieval_holdout.json"
    )

    assert development.split == "development"
    assert holdout.split == "holdout"
    assert len(development.cases) == 30
    assert len(holdout.cases) == 15
    assert {case.language for case in development.cases} == {"ko", "en", "mixed"}
    assert {case.language for case in holdout.cases} == {"ko", "en", "mixed"}
    assert sum(len(case.gold) > 1 for case in development.cases) >= 4
    assert sum(len(case.gold) > 1 for case in holdout.cases) >= 3
    assert {case.id for case in development.cases}.isdisjoint(
        case.id for case in holdout.cases
    )
    assert {case.query.casefold() for case in development.cases}.isdisjoint(
        case.query.casefold() for case in holdout.cases
    )


def test_validate_dataset_against_corpus_accepts_searchable_gold() -> None:
    """Accept a page that exists and has searchable chunk content."""
    corpus = LoadedCorpus(corpus_id="test-corpus", documents=(_document(),))

    validate_dataset_against_corpus(_dataset(), corpus)

    assert _summarize_corpus(corpus) == {
        "corpus_id": "test-corpus",
        "document_count": 1,
        "page_count": 4,
        "excluded_page_count": 1,
        "searchable_page_count": 3,
        "chunk_count": 3,
    }


@pytest.mark.parametrize(
    ("page_number", "message"),
    [
        (2, "uses excluded page 2"),
        (4, "has no searchable content"),
        (5, "exceeds guide page count"),
    ],
)
def test_validate_dataset_against_corpus_rejects_invalid_gold_pages(
    page_number: int,
    message: str,
) -> None:
    """Reject excluded, empty, and out-of-range physical pages.

    Parameters
    ----------
    page_number : int
        Invalid gold page used by the case.
    message : str
        Expected validation error fragment.
    """
    document = _document(searchable_pages=(1, 3))
    corpus = LoadedCorpus(corpus_id="test-corpus", documents=(document,))

    with pytest.raises(ValueError, match=message):
        validate_dataset_against_corpus(_dataset(page_number), corpus)


def test_validate_dataset_against_corpus_rejects_wrong_corpus() -> None:
    """Reject a dataset evaluated against a different corpus version."""
    corpus = LoadedCorpus(corpus_id="other-corpus", documents=(_document(),))

    with pytest.raises(ValueError, match="does not match other-corpus"):
        validate_dataset_against_corpus(_dataset(), corpus)
