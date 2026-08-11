"""Tests for page-aware native PDF text extraction."""

from pathlib import Path
from uuid import UUID

import pymupdf
import pytest

from semiconductor_rag.ingestion import PdfExtractionError, extract_pdf

VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")


def _write_pdf(path: Path, page_texts: list[str]) -> None:
    """Create a small native-text PDF for extraction tests.

    Parameters
    ----------
    path : pathlib.Path
        Destination path.
    page_texts : list[str]
        One text value for each generated page.
    """
    with pymupdf.open() as document:  # type: ignore[no-untyped-call]
        for text in page_texts:
            page = document.new_page(width=300, height=400)
            page.insert_text((40, 60), text, fontsize=12)
        document.save(path)


def test_extract_pdf_preserves_page_order_and_traceability(tmp_path: Path) -> None:
    """Return ordered pages and deterministic identifiers for native text."""
    pdf_path = tmp_path / "sample.pdf"
    _write_pdf(pdf_path, ["Wafer preparation", "Oxidation process"])

    first_result = extract_pdf(pdf_path, VERSION_ID)
    second_result = extract_pdf(pdf_path, VERSION_ID)

    assert [item.page.page_number for item in first_result] == [1, 2]
    assert [item.page.page_id for item in first_result] == [
        item.page.page_id for item in second_result
    ]
    assert first_result[0].elements[0].text == "Wafer preparation"
    assert first_result[1].elements[0].text == "Oxidation process"
    assert first_result[0].elements[0].page_id == first_result[0].page.page_id
    assert first_result[0].elements[0].bbox is not None
    assert first_result[0].page.text_coverage > 0


def test_extract_pdf_keeps_empty_pages(tmp_path: Path) -> None:
    """Represent an empty physical page without inventing text elements."""
    pdf_path = tmp_path / "empty-page.pdf"
    _write_pdf(pdf_path, [""])

    result = extract_pdf(pdf_path, VERSION_ID)

    assert len(result) == 1
    assert result[0].elements == ()
    assert result[0].page.text_coverage == 0.0


def test_extract_pdf_reports_missing_file(tmp_path: Path) -> None:
    """Raise a clear error when the configured PDF path is absent."""
    missing_path = tmp_path / "missing.pdf"

    with pytest.raises(PdfExtractionError, match="does not exist"):
        extract_pdf(missing_path, VERSION_ID)


def test_extract_pdf_reports_unreadable_file(tmp_path: Path) -> None:
    """Raise a clear error when a file is not a readable PDF."""
    invalid_path = tmp_path / "invalid.pdf"
    invalid_path.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(PdfExtractionError, match="Unable to read PDF"):
        extract_pdf(invalid_path, VERSION_ID)
