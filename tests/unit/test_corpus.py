"""Unit tests for verified multi-document corpus loading."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from semiconductor_rag.corpus import (
    CorpusLoadError,
    compute_file_sha256,
    load_corpus,
)


def _write_pdf(path: Path, page_texts: tuple[str, ...]) -> None:
    """Create one native-text PDF fixture.

    Parameters
    ----------
    path : pathlib.Path
        Destination fixture path.
    page_texts : tuple of str
        Text inserted on each physical page.
    """
    with pymupdf.open() as document:  # type: ignore[no-untyped-call]
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)


def _source(
    source_id: str,
    filename: str,
    title: str,
    page_count: int,
    digest: str,
    excluded_pages: list[int] | None = None,
) -> dict[str, object]:
    """Build one valid source catalog mapping.

    Parameters
    ----------
    source_id : str
        Stable source identifier.
    filename : str
        Local PDF filename.
    title : str
        Human-readable source title.
    page_count : int
        Expected physical page count.
    digest : str
        Expected PDF SHA-256.
    excluded_pages : list of int or None, default=None
        Physical pages excluded from search.

    Returns
    -------
    dict[str, object]
        JSON-compatible catalog source mapping.
    """
    return {
        "id": source_id,
        "title": title,
        "publisher": "Test Publisher",
        "language": "en-US",
        "version": "1.0",
        "published_at": "2026-01-01",
        "updated_at": None,
        "landing_page_url": f"https://example.com/{source_id}",
        "download_url": f"https://example.com/{filename}",
        "filename": filename,
        "expected_page_count": page_count,
        "expected_sha256": digest,
        "excluded_pages": excluded_pages or [],
        "license": {
            "identifier": "TEST",
            "reference_url": None,
            "redistribution": "allowed-with-attribution",
            "notice": "Test fixture only.",
        },
    }


def _write_catalog(path: Path, pdf_dir: Path, sources: list[dict[str, object]]) -> None:
    """Write one JSON-compatible YAML catalog fixture.

    Parameters
    ----------
    path : pathlib.Path
        Destination catalog path.
    pdf_dir : pathlib.Path
        Local source directory recorded in the catalog.
    sources : list of dict
        Source entries retained in catalog order.
    """
    catalog = {
        "schema_version": 1,
        "corpus_id": "test-ai-security",
        "title": "Test AI Security Corpus",
        "description": "Deterministic test corpus.",
        "default_output_dir": str(pdf_dir),
        "sources": sources,
    }
    path.write_text(json.dumps(catalog), encoding="utf-8")


def test_load_corpus_preserves_document_identity_and_exclusions(
    tmp_path: Path,
) -> None:
    """Load multiple PDFs without mixing identical physical page numbers."""
    first_path = tmp_path / "first.pdf"
    second_path = tmp_path / "second.pdf"
    _write_pdf(first_path, ("first page", "excluded page", "third page"))
    _write_pdf(second_path, ("second document page one", "second page"))
    catalog_path = tmp_path / "sources.yaml"
    _write_catalog(
        catalog_path,
        tmp_path,
        [
            _source(
                "first-guide",
                first_path.name,
                "First Guide",
                3,
                compute_file_sha256(first_path),
                excluded_pages=[2],
            ),
            _source(
                "second-guide",
                second_path.name,
                "Second Guide",
                2,
                compute_file_sha256(second_path),
            ),
        ],
    )

    corpus = load_corpus(catalog_path)

    assert corpus.corpus_id == "test-ai-security"
    assert len(corpus.documents) == 2
    assert sum(document.page_count for document in corpus.documents) == 5
    assert len(corpus.chunks) == 4
    first_document = corpus.get_document("first-guide")
    second_document = corpus.get_document("second-guide")
    assert first_document is not None
    assert second_document is not None
    assert {chunk.page_start for chunk in first_document.chunks} == {1, 3}
    assert {chunk.page_start for chunk in second_document.chunks} == {1, 2}
    assert first_document.version_id != second_document.version_id
    assert corpus.sources_by_version[first_document.version_id].title == "First Guide"


def test_load_corpus_rejects_checksum_mismatch(tmp_path: Path) -> None:
    """Reject a local file that does not match the pinned source version."""
    pdf_path = tmp_path / "guide.pdf"
    _write_pdf(pdf_path, ("verified page",))
    catalog_path = tmp_path / "sources.yaml"
    _write_catalog(
        catalog_path,
        tmp_path,
        [_source("guide", pdf_path.name, "Guide", 1, "0" * 64)],
    )

    with pytest.raises(CorpusLoadError, match="checksum"):
        load_corpus(catalog_path)


def test_load_corpus_rejects_page_count_mismatch(tmp_path: Path) -> None:
    """Reject a PDF whose physical page count differs from the catalog."""
    pdf_path = tmp_path / "guide.pdf"
    _write_pdf(pdf_path, ("only page",))
    catalog_path = tmp_path / "sources.yaml"
    _write_catalog(
        catalog_path,
        tmp_path,
        [
            _source(
                "guide",
                pdf_path.name,
                "Guide",
                2,
                compute_file_sha256(pdf_path),
            )
        ],
    )

    with pytest.raises(CorpusLoadError, match="has 1 pages; expected 2"):
        load_corpus(catalog_path)
