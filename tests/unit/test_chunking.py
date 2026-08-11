"""Tests for deterministic page-aware text chunking."""

from uuid import UUID, uuid5

import pytest

from semiconductor_rag.domain import Element, ElementType, Page
from semiconductor_rag.ingestion import ExtractedPage, build_page_chunks

VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")


def _make_page(page_number: int, texts: list[str]) -> ExtractedPage:
    """Build one extracted page for chunking tests.

    Parameters
    ----------
    page_number : int
        One-based physical page number.
    texts : list[str]
        Element text values in reading order.

    Returns
    -------
    ExtractedPage
        Valid page and element contracts.
    """
    page_id = uuid5(VERSION_ID, f"page:{page_number}")
    page = Page(
        page_id=page_id,
        version_id=VERSION_ID,
        page_number=page_number,
        width=300,
        height=400,
        text_coverage=0.2 if texts else 0.0,
    )
    elements = tuple(
        Element(
            element_id=uuid5(page_id, f"element:{reading_order}"),
            page_id=page_id,
            element_type=ElementType.PARAGRAPH,
            text=text,
            reading_order=reading_order,
            bbox=(10, 10 + reading_order * 20, 200, 25 + reading_order * 20),
        )
        for reading_order, text in enumerate(texts)
    )
    return ExtractedPage(page=page, elements=elements)


def test_build_page_chunks_never_crosses_page_boundaries() -> None:
    """Keep every chunk traceable to exactly one physical page."""
    pages = (_make_page(1, ["wafer", "oxidation"]), _make_page(2, ["etch"]))

    chunks = build_page_chunks(pages, VERSION_ID, max_characters=100)

    assert [chunk.page_start for chunk in chunks] == [1, 2]
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert chunks[0].text == "wafer\n\noxidation"
    assert chunks[1].text == "etch"


def test_build_page_chunks_splits_between_elements() -> None:
    """Split a page before the next element would exceed the soft limit."""
    pages = (_make_page(1, ["12345", "67890", "abc"]),)

    chunks = build_page_chunks(pages, VERSION_ID, max_characters=12)

    assert [chunk.text for chunk in chunks] == ["12345\n\n67890", "abc"]
    assert [len(chunk.element_ids) for chunk in chunks] == [2, 1]


def test_build_page_chunks_is_deterministic() -> None:
    """Return stable identifiers and hashes for the same ordered content."""
    pages = (_make_page(1, ["증착 공정", "금속 배선"]),)

    first_result = build_page_chunks(pages, VERSION_ID)
    second_result = build_page_chunks(pages, VERSION_ID)

    assert first_result == second_result
    assert first_result[0].token_count > 0
    assert len(first_result[0].content_hash) == 64


def test_build_page_chunks_ignores_empty_pages() -> None:
    """Create no searchable chunk when a page has no native text."""
    chunks = build_page_chunks((_make_page(1, []),), VERSION_ID)

    assert chunks == ()


def test_build_page_chunks_rejects_non_positive_limit() -> None:
    """Reject an invalid character limit before processing pages."""
    with pytest.raises(ValueError, match="must be positive"):
        build_page_chunks((_make_page(1, ["text"]),), VERSION_ID, max_characters=0)
