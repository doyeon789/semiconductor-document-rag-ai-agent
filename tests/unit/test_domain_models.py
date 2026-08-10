"""Unit tests for project-specific domain model invariants."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from semiconductor_rag.domain import (
    Chunk,
    ChunkType,
    Citation,
    CitationSupport,
    Document,
    DocumentLanguage,
    DocumentType,
    DocumentVersion,
    Element,
    ElementType,
    Page,
    Table,
)

SHA256 = "a" * 64


def test_document_rejects_deletion_before_creation() -> None:
    """Reject a deletion timestamp earlier than document creation."""
    created_at = datetime.now(UTC)

    with pytest.raises(ValidationError, match="deleted_at must not be earlier"):
        Document(
            document_id=uuid4(),
            title="Etch Process Guide",
            document_type=DocumentType.PROCESS_DOCUMENT,
            language=DocumentLanguage.ENGLISH,
            created_at=created_at,
            deleted_at=created_at - timedelta(seconds=1),
        )


@pytest.mark.parametrize("page_count", [0, -1])
def test_document_version_requires_positive_page_count(page_count: int) -> None:
    """Reject document versions without a positive physical page count."""
    with pytest.raises(ValidationError):
        DocumentVersion(
            version_id=uuid4(),
            document_id=uuid4(),
            content_sha256=SHA256,
            parser_config_hash=SHA256,
            parser_version="parser-v1",
            page_count=page_count,
            object_key="documents/example.pdf",
        )


@pytest.mark.parametrize("page_number", [0, -1])
def test_page_number_is_one_based(page_number: int) -> None:
    """Reject page numbers outside the one-based PDF coordinate system."""
    with pytest.raises(ValidationError):
        Page(
            page_id=uuid4(),
            version_id=uuid4(),
            page_number=page_number,
            width=612.0,
            height=792.0,
            text_coverage=0.5,
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_page_rejects_invalid_ocr_confidence(confidence: float) -> None:
    """Reject OCR confidence values outside the normalized range."""
    with pytest.raises(ValidationError):
        Page(
            page_id=uuid4(),
            version_id=uuid4(),
            page_number=1,
            width=612.0,
            height=792.0,
            text_coverage=0.5,
            ocr_used=True,
            ocr_confidence=confidence,
        )


def test_element_rejects_reversed_bounding_box() -> None:
    """Reject page coordinates whose maximum corner precedes the minimum."""
    with pytest.raises(ValidationError, match="bounding box must satisfy"):
        Element(
            element_id=uuid4(),
            page_id=uuid4(),
            element_type=ElementType.PARAGRAPH,
            text="Plasma density increases with RF power.",
            reading_order=0,
            bbox=(100.0, 20.0, 10.0, 40.0),
        )


def test_table_rejects_rows_that_do_not_match_header() -> None:
    """Reject normalized table rows that lose their column relationship."""
    with pytest.raises(ValidationError, match="row must match the header width"):
        Table(
            table_id=uuid4(),
            version_id=uuid4(),
            page_id=uuid4(),
            header=["Gas", "Flow"],
            rows=[["Ar"]],
            markdown="| Gas | Flow |",
        )


def test_chunk_rejects_empty_text() -> None:
    """Reject chunks without searchable content."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id=uuid4(),
            version_id=uuid4(),
            chunk_type=ChunkType.TEXT,
            text="   ",
            page_start=1,
            page_end=1,
            token_count=0,
            content_hash=SHA256,
        )


def test_chunk_rejects_reversed_page_range() -> None:
    """Reject chunks whose ending page precedes their starting page."""
    with pytest.raises(ValidationError, match="page_end must be greater"):
        Chunk(
            chunk_id=uuid4(),
            version_id=uuid4(),
            chunk_type=ChunkType.TEXT,
            text="A page-grounded process description.",
            page_start=2,
            page_end=1,
            token_count=5,
            content_hash=SHA256,
        )


def test_citation_preserves_versioned_page_reference() -> None:
    """Keep document, version, chunk, and page identifiers in a citation."""
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()
    citation = Citation(
        citation_id=uuid4(),
        claim_id=uuid4(),
        chunk_id=chunk_id,
        document_id=document_id,
        version_id=version_id,
        page_number=42,
        quote="Check chamber pressure and vacuum valve status.",
        support=CitationSupport.SUPPORTS,
        validation_score=0.98,
    )

    assert citation.document_id == document_id
    assert citation.version_id == version_id
    assert citation.chunk_id == chunk_id
    assert citation.page_number == 42
