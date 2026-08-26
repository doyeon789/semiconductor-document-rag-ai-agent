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


def test_build_page_chunks_inherits_section_context() -> None:
    """Carry a detected section onto later chunks on the same page."""
    pages = (
        _make_page(
            1,
            [
                "2.2. Confabulation",
                "Definition of generated false content.",
                "Risk in consequential decisions.",
            ],
        ),
        _make_page(2, ["Continuation of the same section."]),
    )

    chunks = build_page_chunks(
        pages,
        VERSION_ID,
        max_characters=45,
    )

    page_one_chunks = tuple(chunk for chunk in chunks if chunk.page_start == 1)
    page_two_chunk = next(chunk for chunk in chunks if chunk.page_start == 2)

    assert all(
        chunk.section_path == ["2.2. Confabulation"] for chunk in page_one_chunks
    )
    assert all(
        chunk.retrieval_text.startswith("2.2. Confabulation")
        for chunk in page_one_chunks
    )
    assert page_two_chunk.section_path == []


def test_build_page_chunks_rejects_dates_as_section_headings() -> None:
    """Do not treat a dotted release date as a structural heading."""
    chunks = build_page_chunks(
        (
            _make_page(
                1,
                ["2026.08.25 release notes", "08.25 release notes", "Body text"],
            ),
        ),
        VERSION_ID,
    )

    assert chunks[0].section_path == []


def test_build_page_chunks_rejects_numbered_list_sentences() -> None:
    """Do not mistake a multi-level checklist item for a section heading."""
    chunks = build_page_chunks(
        (
            _make_page(
                1,
                [
                    "1.2 Previous Section",
                    "Previous body",
                    "3.2.1 Prompt injection defenses are verified? □ □ □",
                    "Continuation after the checklist item.",
                ],
            ),
        ),
        VERSION_ID,
        max_characters=40,
    )

    assert all(len(chunk.section_path) <= 1 for chunk in chunks)
    assert all(
        "3.2.1" not in section for chunk in chunks for section in chunk.section_path
    )
    assert chunks[-1].section_path == ["1.2 Previous Section"]


def test_build_page_chunks_defers_mixed_language_numbered_titles() -> None:
    """Avoid Korean checklist ambiguity until heading font metadata exists."""
    chunks = build_page_chunks(
        (_make_page(1, ["2.2 한국어 절 제목", "Section body"]),),
        VERSION_ID,
        max_characters=20,
    )

    assert all(chunk.section_path == [] for chunk in chunks)


def test_build_page_chunks_inherits_nist_function_table_caption() -> None:
    """Carry a high-confidence NIST function caption to its continuation."""
    caption = "Table 2: Categories and subcategories for the MAP function."
    chunks = build_page_chunks(
        (_make_page(1, [caption, "MAP 1.1 context.", "MAP 1.2 context."]),),
        VERSION_ID,
        max_characters=30,
    )

    assert all(chunk.section_path == [caption] for chunk in chunks)
    assert chunks[-1].retrieval_text.startswith(caption)


def test_build_page_chunks_does_not_inherit_across_physical_pages() -> None:
    """Keep conservative section context within one physical page."""
    pages = (
        _make_page(1, ["2.2. Confabulation", "Section body"]),
        _make_page(2, ["Body on the next physical page"]),
    )

    chunks = build_page_chunks(
        pages,
        VERSION_ID,
    )

    page_two = next(chunk for chunk in chunks if chunk.page_start == 2)
    assert page_two.section_path == []


def test_section_context_preserves_chunk_identity_and_raw_boundaries() -> None:
    """Pin IDs, hashes, token counts, and raw boundaries across context changes."""
    chunks = build_page_chunks(
        (
            _make_page(
                1,
                [
                    "2.2. Confabulation",
                    "Definition of generated false content.",
                    "Risk in consequential decisions.",
                ],
            ),
        ),
        VERSION_ID,
        max_characters=45,
    )

    assert [chunk.text for chunk in chunks] == [
        "2.2. Confabulation",
        "Definition of generated false content.",
        "Risk in consequential decisions.",
    ]
    assert [str(chunk.chunk_id) for chunk in chunks] == [
        "42850203-fa5f-5e55-87b8-9c12342b0096",
        "8e211370-c0be-52b9-bb8e-b392980f49e0",
        "e41b6c5a-d184-526a-aa45-5293b6d7585e",
    ]
    assert [chunk.content_hash for chunk in chunks] == [
        "c1a4d370d87b9c6958967e2e439808ef3d9231c37b7c7d233968f1f5bb938d98",
        "d669322e9c589bcd32121413f5f1131f07af25cd8e73c0b180ad08cac7c97779",
        "cf42022556ffcfa5b810ab72e70d6669d29fac7535600594f5a77a1764f4d42b",
    ]
    assert [chunk.token_count for chunk in chunks] == [5, 6, 5]
    assert all(chunk.page_start == chunk.page_end == 1 for chunk in chunks)
    assert all(len(chunk.element_ids) == 1 for chunk in chunks)


def test_build_page_chunks_ignores_empty_pages() -> None:
    """Create no searchable chunk when a page has no native text."""
    chunks = build_page_chunks((_make_page(1, []),), VERSION_ID)

    assert chunks == ()


def test_build_page_chunks_rejects_non_positive_limit() -> None:
    """Reject an invalid character limit before processing pages."""
    with pytest.raises(ValueError, match="must be positive"):
        build_page_chunks((_make_page(1, ["text"]),), VERSION_ID, max_characters=0)
