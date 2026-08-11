"""Integration test for the native PDF-to-chunk ingestion path."""

from pathlib import Path
from uuid import UUID

import pymupdf

from semiconductor_rag.ingestion import build_page_chunks, extract_pdf

VERSION_ID = UUID("44444444-4444-4444-8444-444444444444")


def _write_process_pdf(path: Path) -> None:
    """Create a three-page semiconductor process PDF fixture.

    Parameters
    ----------
    path : pathlib.Path
        Destination path for the temporary PDF.
    """
    page_lines = [
        ["Wafer manufacturing", "Crystal growth and slicing"],
        ["Thermal oxidation", "Dry and wet oxidation"],
        ["Selective etching", "Transfer patterns into material"],
    ]
    with pymupdf.open() as document:  # type: ignore[no-untyped-call]
        for lines in page_lines:
            page = document.new_page(width=400, height=500)
            for line_number, line in enumerate(lines):
                page.insert_text((50, 70 + line_number * 80), line, fontsize=12)
        document.save(path)


def test_pdf_ingestion_keeps_every_element_traceable(tmp_path: Path) -> None:
    """Convert all PDF pages and elements into deterministic local chunks."""
    pdf_path = tmp_path / "semiconductor-processes.pdf"
    _write_process_pdf(pdf_path)

    pages = extract_pdf(pdf_path, VERSION_ID)
    chunks = build_page_chunks(pages, VERSION_ID, max_characters=60)
    repeated_chunks = build_page_chunks(pages, VERSION_ID, max_characters=60)

    assert [item.page.page_number for item in pages] == [1, 2, 3]
    assert {chunk.page_start for chunk in chunks} == {1, 2, 3}
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert any("Thermal oxidation" in chunk.text for chunk in chunks)

    source_element_ids = {
        element.element_id for item in pages for element in item.elements
    }
    linked_element_ids = [
        element_id for chunk in chunks for element_id in chunk.element_ids
    ]
    assert set(linked_element_ids) == source_element_ids
    assert len(linked_element_ids) == len(source_element_ids)
    assert chunks == repeated_chunks
