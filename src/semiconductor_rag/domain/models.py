"""Validated data contracts for document ingestion and citation tracking."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _validate_bounding_box(
    value: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Validate a bounding box expressed as ``(x0, y0, x1, y1)``.

    Parameters
    ----------
    value : tuple[float, float, float, float]
        Bounding box coordinates in page space.

    Returns
    -------
    tuple[float, float, float, float]
        The validated bounding box.

    Raises
    ------
    ValueError
        If a coordinate is not finite or the maximum corner precedes the
        minimum corner.
    """
    x0, y0, x1, y1 = value
    if not all(isfinite(coordinate) for coordinate in value):
        raise ValueError("bounding box coordinates must be finite")
    if x1 < x0 or y1 < y0:
        raise ValueError("bounding box must satisfy x1 >= x0 and y1 >= y0")
    return value


NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
BoundingBox = Annotated[
    tuple[float, float, float, float],
    AfterValidator(_validate_bounding_box),
]


class DomainModel(BaseModel):
    """Provide strict shared validation for public domain contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentType(StrEnum):
    """Classify supported source documents."""

    PAPER = "paper"
    MANUAL = "manual"
    PROCESS_DOCUMENT = "process_doc"
    DATASHEET = "datasheet"
    OTHER = "other"


class DocumentLanguage(StrEnum):
    """Describe the primary language used by a document."""

    KOREAN = "ko"
    ENGLISH = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class IngestionStatus(StrEnum):
    """Represent a document version's ingestion lifecycle state."""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    INDEXING = "indexing"
    READY = "ready"
    PARSE_FAILED = "parse_failed"
    INDEX_FAILED = "index_failed"
    REINDEXING = "reindexing"


class ElementType(StrEnum):
    """Classify parser-produced page elements."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CAPTION = "caption"
    FOOTER = "footer"
    HEADER = "header"


class ChunkType(StrEnum):
    """Classify searchable chunk representations."""

    TEXT = "text"
    TABLE = "table"
    CAPTION = "caption"


class CitationSupport(StrEnum):
    """Describe how cited evidence relates to a claim."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT_ONLY = "context_only"


class Document(DomainModel):
    """Represent a logical document across one or more file versions."""

    document_id: UUID
    title: NonEmptyString
    document_type: DocumentType
    language: DocumentLanguage
    source_uri: NonEmptyString | None = None
    license_type: NonEmptyString | None = None
    access_scope: NonEmptyString = "public-demo"
    created_at: AwareDatetime
    deleted_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_deletion_time(self) -> Document:
        """Ensure document deletion cannot precede document creation.

        Returns
        -------
        Document
            The validated document.

        Raises
        ------
        ValueError
            If ``deleted_at`` is earlier than ``created_at``.
        """
        if self.deleted_at is not None and self.deleted_at < self.created_at:
            raise ValueError("deleted_at must not be earlier than created_at")
        return self


class DocumentVersion(DomainModel):
    """Represent a file processed with one parser configuration."""

    version_id: UUID
    document_id: UUID
    content_sha256: Sha256Digest
    parser_config_hash: Sha256Digest
    parser_version: NonEmptyString
    page_count: Annotated[int, Field(ge=1)]
    status: IngestionStatus = IngestionStatus.PENDING
    object_key: NonEmptyString
    is_active: bool = False


class Page(DomainModel):
    """Represent one physical, one-based PDF page."""

    page_id: UUID
    version_id: UUID
    page_number: Annotated[int, Field(ge=1)]
    printed_page_label: NonEmptyString | None = None
    width: Annotated[float, Field(gt=0.0)]
    height: Annotated[float, Field(gt=0.0)]
    text_coverage: Confidence
    ocr_used: bool = False
    ocr_confidence: Confidence | None = None
    image_object_key: NonEmptyString | None = None


class Element(DomainModel):
    """Represent the smallest parser-produced layout unit on a page."""

    element_id: UUID
    page_id: UUID
    element_type: ElementType
    text: NonEmptyString
    reading_order: Annotated[int, Field(ge=0)]
    bbox: BoundingBox | None = None
    parser_confidence: Confidence | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


TableCell = str | int | float | bool | None


class Table(DomainModel):
    """Preserve a table's normalized structure and searchable rendering."""

    table_id: UUID
    version_id: UUID
    page_id: UUID
    caption: NonEmptyString | None = None
    header: list[NonEmptyString]
    rows: list[list[TableCell]]
    markdown: NonEmptyString
    bbox: BoundingBox | None = None
    spans_pages: bool = False

    @model_validator(mode="after")
    def validate_row_widths(self) -> Table:
        """Ensure normalized rows align with the declared table header.

        Returns
        -------
        Table
            The validated table.

        Raises
        ------
        ValueError
            If a row contains a different number of cells than the header.
        """
        header_width = len(self.header)
        if any(len(row) != header_width for row in self.rows):
            raise ValueError("every table row must match the header width")
        return self


class Chunk(DomainModel):
    """Represent searchable content that remains traceable to PDF pages."""

    chunk_id: UUID
    version_id: UUID
    chunk_type: ChunkType
    text: NonEmptyString
    element_ids: list[UUID] = Field(default_factory=list)
    page_start: Annotated[int, Field(ge=1)]
    page_end: Annotated[int, Field(ge=1)]
    section_path: list[NonEmptyString] = Field(default_factory=list)
    token_count: Annotated[int, Field(ge=0)]
    content_hash: Sha256Digest
    embedding_version: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_page_range(self) -> Chunk:
        """Ensure the chunk's ending page follows its starting page.

        Returns
        -------
        Chunk
            The validated chunk.

        Raises
        ------
        ValueError
            If ``page_end`` is lower than ``page_start``.
        """
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class Citation(DomainModel):
    """Connect one answer claim to versioned evidence on a PDF page."""

    citation_id: UUID
    claim_id: UUID
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    page_number: Annotated[int, Field(ge=1)]
    quote: NonEmptyString
    bbox: BoundingBox | None = None
    support: CitationSupport
    validation_score: Confidence | None = None
