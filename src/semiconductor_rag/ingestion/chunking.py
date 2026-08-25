"""Build deterministic searchable chunks without crossing PDF pages."""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import UUID, uuid5

from semiconductor_rag.domain import Chunk, ChunkType, Element
from semiconductor_rag.ingestion.pdf import ExtractedPage

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
NUMBERED_SECTION_PATTERN = re.compile(
    r"^[1-9]\d?\.[1-9]\d?\.?\s+\S(?:.*\S)?$",
    flags=re.UNICODE,
)
NIST_TABLE_SECTION_PATTERN = re.compile(
    r"^Table\s+\d+:.*\b(?:GOVERN|MAP|MEASURE|MANAGE)\s+function\b",
    flags=re.IGNORECASE,
)
MAX_NUMBERED_SECTION_HEADING_CHARACTERS = 80
MAX_TABLE_SECTION_HEADING_CHARACTERS = 180
NUMBERED_SECTION_NOISE_MARKERS = ("?", "□", "○", "http://", "https://", "...")


def build_page_chunks(
    pages: tuple[ExtractedPage, ...],
    version_id: UUID,
    max_characters: int = 1_200,
) -> tuple[Chunk, ...]:
    """Combine ordered elements into deterministic page-local chunks.

    Parameters
    ----------
    pages : tuple[ExtractedPage, ...]
        Extracted pages to chunk.
    version_id : uuid.UUID
        Parent document version identifier.
    max_characters : int, default=1200
        Soft character limit. A single element longer than this limit remains
        intact so source traceability is not lost.
    Returns
    -------
    tuple[Chunk, ...]
        Searchable chunks ordered by page and position.

    Raises
    ------
    ValueError
        If ``max_characters`` is not positive.
    """
    if max_characters < 1:
        raise ValueError("max_characters must be positive")

    chunks: list[Chunk] = []
    for extracted_page in sorted(pages, key=lambda item: item.page.page_number):
        page_number = extracted_page.page.page_number
        page_elements = sorted(
            extracted_page.elements,
            key=lambda element: element.reading_order,
        )
        groups = _group_elements(page_elements, max_characters)
        contextual_groups = _attach_section_context(groups)
        chunks.extend(
            _build_chunk(
                elements=group,
                version_id=version_id,
                page_number=page_number,
                page_chunk_index=page_chunk_index,
                section_path=section_headings,
            )
            for page_chunk_index, (section_headings, group) in enumerate(
                contextual_groups
            )
        )
    return tuple(chunks)


def _group_elements(
    elements: list[Element],
    max_characters: int,
) -> tuple[tuple[Element, ...], ...]:
    """Group elements up to a soft character limit.

    Parameters
    ----------
    elements : list[Element]
        Elements from one physical page in reading order.
    max_characters : int
        Soft maximum length for joined element text.

    Returns
    -------
    tuple[tuple[Element, ...], ...]
        Non-empty groups that never cross a page boundary.
    """
    groups: list[tuple[Element, ...]] = []
    current: list[Element] = []
    current_length = 0

    for element in elements:
        separator_length = 2 if current else 0
        next_length = current_length + separator_length + len(element.text)
        if current and next_length > max_characters:
            groups.append(tuple(current))
            current = []
            current_length = 0
            separator_length = 0

        current.append(element)
        current_length += separator_length + len(element.text)

    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _attach_section_context(
    groups: tuple[tuple[Element, ...], ...],
) -> tuple[tuple[tuple[str, ...], tuple[Element, ...]], ...]:
    """Attach headings without changing established raw chunk boundaries.

    Parameters
    ----------
    groups : tuple[tuple[Element, ...], ...]
        Page-local element groups produced by character-aware chunking.
    Returns
    -------
    tuple
        At most one context heading paired with each unchanged group.
    """
    contextual_groups: list[tuple[tuple[str, ...], tuple[Element, ...]]] = []
    active_section_heading: str | None = None
    for group in groups:
        detected_headings = tuple(
            element.text for element in group if _is_section_heading(element.text)
        )
        group_section_heading = (
            detected_headings[0] if detected_headings else active_section_heading
        )
        section_path = (
            (group_section_heading,) if group_section_heading is not None else ()
        )
        contextual_groups.append((section_path, group))
        if detected_headings:
            active_section_heading = detected_headings[-1]
    return tuple(contextual_groups)


def _is_section_heading(text: str) -> bool:
    """Return whether one extracted block is a conservative section title.

    Parameters
    ----------
    text : str
        Normalized PDF block text.

    Returns
    -------
    bool
        ``True`` for short ASCII two-level headings or NIST function-table
        captions. Mixed-language numbered blocks remain excluded until font
        metadata can separate headings from checklist rows reliably.
    """
    normalized_text = text.casefold()
    numbered_heading = (
        text.isascii()
        and len(text) <= MAX_NUMBERED_SECTION_HEADING_CHARACTERS
        and not any(
            marker in normalized_text for marker in NUMBERED_SECTION_NOISE_MARKERS
        )
        and NUMBERED_SECTION_PATTERN.fullmatch(text) is not None
        and not text.endswith(".")
    )
    table_heading = (
        len(text) <= MAX_TABLE_SECTION_HEADING_CHARACTERS
        and NIST_TABLE_SECTION_PATTERN.match(text) is not None
    )
    return numbered_heading or table_heading


def _build_chunk(
    elements: tuple[Element, ...],
    version_id: UUID,
    page_number: int,
    page_chunk_index: int,
    section_path: tuple[str, ...],
) -> Chunk:
    """Create one validated chunk from a non-empty element group.

    Parameters
    ----------
    elements : tuple[Element, ...]
        Ordered elements from one page.
    version_id : uuid.UUID
        Parent document version identifier.
    page_number : int
        One-based physical page number.
    page_chunk_index : int
        Zero-based chunk position within the page.
    section_path : tuple of str
        Search-only section heading inherited within the physical page.

    Returns
    -------
    Chunk
        Traceable text chunk with deterministic identity and content hash.
    """
    text = "\n\n".join(element.text for element in elements)
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    chunk_id = uuid5(
        version_id,
        f"chunk:{page_number}:{page_chunk_index}:{content_hash}",
    )
    return Chunk(
        chunk_id=chunk_id,
        version_id=version_id,
        chunk_type=ChunkType.TEXT,
        text=text,
        element_ids=[element.element_id for element in elements],
        page_start=page_number,
        page_end=page_number,
        section_path=list(section_path),
        token_count=len(TOKEN_PATTERN.findall(text)),
        content_hash=content_hash,
    )
