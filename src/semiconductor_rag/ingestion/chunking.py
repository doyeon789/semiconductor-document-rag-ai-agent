"""Build deterministic searchable chunks without crossing PDF pages."""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import UUID, uuid5

from semiconductor_rag.domain import Chunk, ChunkType, Element
from semiconductor_rag.ingestion.pdf import ExtractedPage

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


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
        page_elements = sorted(
            extracted_page.elements,
            key=lambda element: element.reading_order,
        )
        groups = _group_elements(page_elements, max_characters)
        chunks.extend(
            _build_chunk(
                elements=group,
                version_id=version_id,
                page_number=extracted_page.page.page_number,
                page_chunk_index=page_chunk_index,
            )
            for page_chunk_index, group in enumerate(groups)
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


def _build_chunk(
    elements: tuple[Element, ...],
    version_id: UUID,
    page_number: int,
    page_chunk_index: int,
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
        token_count=len(TOKEN_PATTERN.findall(text)),
        content_hash=content_hash,
    )
