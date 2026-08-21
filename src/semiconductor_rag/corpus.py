"""Load and validate the versioned public AI security PDF corpus."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from semiconductor_rag.domain import Chunk, DocumentSource
from semiconductor_rag.ingestion import (
    PdfExtractionError,
    build_page_chunks,
    extract_pdf,
)

DEFAULT_CATALOG_PATH = Path("data/corpus/sources.yaml")
CORPUS_PARSER_VERSION = "pymupdf-page-v1"
FILE_HASH_CHUNK_SIZE = 1024 * 1024


class SourceLicense(BaseModel):
    """Describe the recorded redistribution terms for one source document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: str = Field(min_length=1)
    reference_url: HttpUrl | None = None
    redistribution: Literal[
        "allowed-with-attribution",
        "allowed-with-license",
        "verify-before-redistribution",
    ]
    notice: str = Field(min_length=1)


class CorpusSource(BaseModel):
    """Describe one versioned PDF source and its official locations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    version: str = Field(min_length=1)
    published_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    updated_at: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    landing_page_url: HttpUrl
    download_url: HttpUrl | None = None
    filename: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*\.pdf$")
    expected_page_count: int | None = Field(default=None, ge=1)
    expected_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    excluded_pages: tuple[int, ...] = ()
    license: SourceLicense


class CorpusCatalog(BaseModel):
    """Describe a reproducible collection of public PDF sources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    corpus_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    default_output_dir: Path
    sources: tuple[CorpusSource, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """Group one verified source with its local searchable content.

    Parameters
    ----------
    source : DocumentSource
        Public metadata exposed in search and Citation responses.
    version_id : uuid.UUID
        Stable identifier derived from source ID, file hash, and parser version.
    pdf_path : pathlib.Path
        Verified local PDF path used by the document endpoint.
    page_count : int
        Physical page count before exclusions.
    excluded_pages : tuple of int
        Physical pages intentionally excluded from search.
    chunks : tuple of Chunk
        Searchable page-local chunks for the document.
    """

    source: DocumentSource
    version_id: UUID
    pdf_path: Path
    page_count: int
    excluded_pages: tuple[int, ...]
    chunks: tuple[Chunk, ...]


@dataclass(frozen=True, slots=True)
class LoadedCorpus:
    """Expose verified documents and their combined search index input.

    Parameters
    ----------
    corpus_id : str
        Stable catalog identifier.
    documents : tuple of CorpusDocument
        Verified documents retained in catalog order.
    """

    corpus_id: str
    documents: tuple[CorpusDocument, ...]

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        """Return every searchable chunk in catalog order.

        Returns
        -------
        tuple of Chunk
            Flattened chunks from every loaded document.
        """
        return tuple(chunk for document in self.documents for chunk in document.chunks)

    @property
    def sources_by_version(self) -> dict[UUID, DocumentSource]:
        """Map each loaded version to its public source metadata.

        Returns
        -------
        dict[uuid.UUID, DocumentSource]
            Version lookup used to enrich retrieval hits.
        """
        return {document.version_id: document.source for document in self.documents}

    def get_document(self, document_id: str) -> CorpusDocument | None:
        """Return one document by its catalog source identifier.

        Parameters
        ----------
        document_id : str
            Stable catalog source identifier.

        Returns
        -------
        CorpusDocument or None
            Matching document, or ``None`` when the identifier is unknown.
        """
        return next(
            (
                document
                for document in self.documents
                if document.source.document_id == document_id
            ),
            None,
        )


class CorpusLoadError(RuntimeError):
    """Report that the configured local corpus cannot be indexed safely."""


def load_catalog(path: Path) -> CorpusCatalog:
    """Load and validate a public PDF source catalog.

    Parameters
    ----------
    path : pathlib.Path
        YAML catalog path.

    Returns
    -------
    CorpusCatalog
        Validated catalog and source metadata.

    Raises
    ------
    ValueError
        If the YAML root, identifiers, filenames, or page exclusions are
        invalid.
    """
    raw_catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_catalog, dict):
        raise ValueError("corpus catalog root must be a mapping")
    catalog = CorpusCatalog.model_validate(raw_catalog)
    source_ids = [source.id for source in catalog.sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("corpus source ids must be unique")
    filenames = [source.filename for source in catalog.sources]
    if len(filenames) != len(set(filenames)):
        raise ValueError("corpus source filenames must be unique")
    for source in catalog.sources:
        if any(page < 1 for page in source.excluded_pages):
            raise ValueError(f"source {source.id} excluded pages must be positive")
        if len(source.excluded_pages) != len(set(source.excluded_pages)):
            raise ValueError(f"source {source.id} excluded pages must be unique")
        if source.expected_page_count is not None and any(
            page > source.expected_page_count for page in source.excluded_pages
        ):
            raise ValueError(f"source {source.id} excluded pages exceed its page count")
    return catalog


def load_corpus(
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    pdf_dir: Path | None = None,
    max_chunk_characters: int = 1_200,
) -> LoadedCorpus:
    """Verify and load every catalog PDF into page-aware chunks.

    Parameters
    ----------
    catalog_path : pathlib.Path, default=DEFAULT_CATALOG_PATH
        Versioned public source catalog.
    pdf_dir : pathlib.Path or None, default=None
        Override for the catalog's local PDF directory.
    max_chunk_characters : int, default=1200
        Soft maximum passed to page-local chunking.

    Returns
    -------
    LoadedCorpus
        Verified documents and combined searchable chunks.

    Raises
    ------
    CorpusLoadError
        If a file, checksum, PDF signature, page count, or searchable content
        does not match the catalog.
    ValueError
        If ``max_chunk_characters`` is not positive.
    """
    if max_chunk_characters < 1:
        raise ValueError("max_chunk_characters must be positive")
    catalog = load_catalog(catalog_path)
    source_dir = pdf_dir or catalog.default_output_dir
    documents = tuple(
        _load_document(source, source_dir, max_chunk_characters)
        for source in catalog.sources
    )
    return LoadedCorpus(corpus_id=catalog.corpus_id, documents=documents)


def compute_file_sha256(path: Path) -> str:
    """Calculate one file's SHA-256 without loading it fully into memory.

    Parameters
    ----------
    path : pathlib.Path
        File whose digest is required.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = sha256()
    with path.open("rb") as source_file:
        while block := source_file.read(FILE_HASH_CHUNK_SIZE):
            digest.update(block)
    return digest.hexdigest()


def _load_document(
    source: CorpusSource,
    pdf_dir: Path,
    max_chunk_characters: int,
) -> CorpusDocument:
    """Verify, extract, and chunk one catalog source.

    Parameters
    ----------
    source : CorpusSource
        Catalog metadata with fixed checksum and page count.
    pdf_dir : pathlib.Path
        Directory containing the downloaded source file.
    max_chunk_characters : int
        Soft page chunk character limit.

    Returns
    -------
    CorpusDocument
        Verified document metadata and searchable chunks.

    Raises
    ------
    CorpusLoadError
        If required verification metadata or local content is invalid.
    """
    if source.expected_sha256 is None or source.expected_page_count is None:
        raise CorpusLoadError(
            f"source {source.id} requires a checksum and page count before loading"
        )
    pdf_path = pdf_dir / source.filename
    if not pdf_path.is_file():
        raise CorpusLoadError(f"source {source.id} PDF is missing: {pdf_path}")
    try:
        with pdf_path.open("rb") as pdf_file:
            signature = pdf_file.read(5)
    except OSError as exc:
        raise CorpusLoadError(f"source {source.id} PDF cannot be read") from exc
    if signature != b"%PDF-":
        raise CorpusLoadError(f"source {source.id} is not a PDF file")
    actual_sha256 = compute_file_sha256(pdf_path)
    if actual_sha256 != source.expected_sha256:
        raise CorpusLoadError(f"source {source.id} checksum does not match the catalog")

    version_id = uuid5(
        NAMESPACE_URL,
        f"{source.id}:{actual_sha256}:{CORPUS_PARSER_VERSION}",
    )
    try:
        pages = extract_pdf(pdf_path, version_id)
    except PdfExtractionError as exc:
        raise CorpusLoadError(f"source {source.id} PDF cannot be extracted") from exc
    if len(pages) != source.expected_page_count:
        raise CorpusLoadError(
            f"source {source.id} has {len(pages)} pages; "
            f"expected {source.expected_page_count}"
        )
    excluded_pages = frozenset(source.excluded_pages)
    searchable_pages = tuple(
        page for page in pages if page.page.page_number not in excluded_pages
    )
    chunks = build_page_chunks(
        searchable_pages,
        version_id,
        max_characters=max_chunk_characters,
    )
    if not chunks:
        raise CorpusLoadError(f"source {source.id} contains no searchable text")
    return CorpusDocument(
        source=DocumentSource(
            document_id=source.id,
            title=source.title,
            publisher=source.publisher,
            language=source.language,
            version=source.version,
        ),
        version_id=version_id,
        pdf_path=pdf_path,
        page_count=len(pages),
        excluded_pages=source.excluded_pages,
        chunks=chunks,
    )
