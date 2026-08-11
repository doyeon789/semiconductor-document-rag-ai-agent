"""Extract page-aware text elements from local PDF documents."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias
from uuid import UUID, uuid5

import pymupdf

from semiconductor_rag.domain import Element, ElementType, Page

TextBlock: TypeAlias = tuple[float, float, float, float, str, int]


class PdfExtractionError(RuntimeError):
    """Report that a local PDF could not be read into page elements."""


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """Group one page contract with its ordered text elements.

    Parameters
    ----------
    page : Page
        Physical page metadata.
    elements : tuple[Element, ...]
        Native text blocks in reading order.
    """

    page: Page
    elements: tuple[Element, ...]


def extract_pdf(pdf_path: str | Path, version_id: UUID) -> tuple[ExtractedPage, ...]:
    """Extract page metadata and ordered native-text blocks from a PDF.

    Parameters
    ----------
    pdf_path : str | pathlib.Path
        Local path to the PDF fixture.
    version_id : uuid.UUID
        Stable version identifier used to derive page and element identifiers.

    Returns
    -------
    tuple[ExtractedPage, ...]
        Extracted pages in one-based page order.

    Raises
    ------
    PdfExtractionError
        If the file is missing, unreadable, encrypted, or contains no pages.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise PdfExtractionError(f"PDF file does not exist: {path}")

    try:
        with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
            if document.needs_pass:
                raise PdfExtractionError(f"PDF requires a password: {path}")
            if document.page_count < 1:
                raise PdfExtractionError(f"PDF contains no pages: {path}")
            return tuple(
                _extract_page(document.load_page(index), version_id, index + 1)
                for index in range(document.page_count)
            )
    except PdfExtractionError:
        raise
    except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
        raise PdfExtractionError(f"Unable to read PDF: {path}") from exc


def _extract_page(
    source_page: pymupdf.Page,
    version_id: UUID,
    page_number: int,
) -> ExtractedPage:
    """Convert one PyMuPDF page into domain contracts.

    Parameters
    ----------
    source_page : pymupdf.Page
        Open PyMuPDF page.
    version_id : uuid.UUID
        Parent document version identifier.
    page_number : int
        One-based physical page number.

    Returns
    -------
    ExtractedPage
        Page metadata and native text elements.

    Raises
    ------
    PdfExtractionError
        If text blocks cannot be read from the page.
    """
    try:
        blocks = _read_text_blocks(source_page)
    except (RuntimeError, ValueError) as exc:
        raise PdfExtractionError(f"Unable to read PDF page {page_number}") from exc

    page_id = uuid5(version_id, f"page:{page_number}")
    elements = tuple(
        Element(
            element_id=uuid5(page_id, f"element:{reading_order}"),
            page_id=page_id,
            element_type=ElementType.PARAGRAPH,
            text=text,
            reading_order=reading_order,
            bbox=(x0, y0, x1, y1),
            parser_confidence=1.0,
            metadata={"source": "pymupdf", "block_number": block_number},
        )
        for reading_order, (x0, y0, x1, y1, text, block_number) in enumerate(blocks)
    )
    width = float(source_page.rect.width)
    height = float(source_page.rect.height)
    page = Page(
        page_id=page_id,
        version_id=version_id,
        page_number=page_number,
        width=width,
        height=height,
        text_coverage=_calculate_text_coverage(blocks, width, height),
        ocr_used=False,
    )
    return ExtractedPage(page=page, elements=elements)


def _read_text_blocks(source_page: pymupdf.Page) -> tuple[TextBlock, ...]:
    """Read normalized text blocks in top-left reading order.

    Parameters
    ----------
    source_page : pymupdf.Page
        Open PyMuPDF page.

    Returns
    -------
    tuple[TextBlock, ...]
        Bounding boxes, text, and parser block numbers.
    """
    blocks: list[TextBlock] = []
    for raw_block in source_page.get_text(  # type: ignore[no-untyped-call]
        "blocks", sort=True
    ):
        if len(raw_block) < 7 or int(raw_block[6]) != 0:
            continue
        text = _normalize_text(str(raw_block[4]))
        if not text:
            continue
        blocks.append(
            (
                float(raw_block[0]),
                float(raw_block[1]),
                float(raw_block[2]),
                float(raw_block[3]),
                text,
                int(raw_block[5]),
            )
        )
    return tuple(blocks)


def _normalize_text(value: str) -> str:
    """Normalize Unicode and repeated whitespace without changing symbols.

    Parameters
    ----------
    value : str
        Raw parser text.

    Returns
    -------
    str
        Search-friendly text with stable whitespace.
    """
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _calculate_text_coverage(
    blocks: tuple[TextBlock, ...],
    page_width: float,
    page_height: float,
) -> float:
    """Estimate the page area occupied by native text blocks.

    Parameters
    ----------
    blocks : tuple[TextBlock, ...]
        Native text blocks.
    page_width : float
        Page width in PDF points.
    page_height : float
        Page height in PDF points.

    Returns
    -------
    float
        Coverage ratio clamped to the inclusive range from zero to one.
    """
    page_area = page_width * page_height
    if page_area <= 0:
        return 0.0
    block_area = sum(
        max(0.0, x1 - x0) * max(0.0, y1 - y0) for x0, y0, x1, y1, _, _ in blocks
    )
    return min(1.0, block_area / page_area)
