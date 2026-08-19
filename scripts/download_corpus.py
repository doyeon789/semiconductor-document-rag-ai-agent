"""Download redistributable public PDF sources into the ignored local corpus."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

DEFAULT_CATALOG_PATH = Path("data/corpus/sources.yaml")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
USER_AGENT = "ai-security-document-rag/0.1 (+public-corpus-downloader)"


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
class DownloadResult:
    """Record one local download or manual-download decision."""

    source_id: str
    status: Literal["downloaded", "existing", "manual-download-required"]
    path: str | None
    sha256: str | None
    size_bytes: int | None
    landing_page_url: str
    download_url: str | None


class CorpusDownloadError(RuntimeError):
    """Report a public corpus download or PDF validation failure."""


def parse_args() -> argparse.Namespace:
    """Parse catalog selection and local output arguments.

    Returns
    -------
    argparse.Namespace
        Parsed list, selection, output, and overwrite options.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--list", action="store_true", dest="list_sources")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", dest="download_all")
    selection.add_argument("--source", action="append", dest="source_ids")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


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
        If the YAML root is not a mapping or source identifiers repeat.
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
    return catalog


def select_sources(
    catalog: CorpusCatalog,
    source_ids: list[str] | None,
    download_all: bool,
) -> tuple[CorpusSource, ...]:
    """Select catalog sources while rejecting unknown identifiers.

    Parameters
    ----------
    catalog : CorpusCatalog
        Validated source catalog.
    source_ids : list of str or None
        Explicit source identifiers requested by the caller.
    download_all : bool
        Whether to select every catalog entry.

    Returns
    -------
    tuple of CorpusSource
        Sources retained in catalog order.

    Raises
    ------
    ValueError
        If no download selection is provided or an identifier is unknown.
    """
    if download_all:
        return catalog.sources
    if not source_ids:
        raise ValueError("choose --all or at least one --source")
    requested_ids = set(source_ids)
    known_ids = {source.id for source in catalog.sources}
    unknown_ids = requested_ids - known_ids
    if unknown_ids:
        unknown_text = ", ".join(sorted(unknown_ids))
        raise ValueError(f"unknown corpus source ids: {unknown_text}")
    return tuple(source for source in catalog.sources if source.id in requested_ids)


def download_source(
    source: CorpusSource,
    output_dir: Path,
    overwrite: bool = False,
    timeout_seconds: float = 60.0,
) -> DownloadResult:
    """Download one direct PDF source and verify its file signature.

    Parameters
    ----------
    source : CorpusSource
        Source metadata and optional direct download URL.
    output_dir : pathlib.Path
        Ignored local directory that receives the PDF.
    overwrite : bool, default=False
        Replace an existing local PDF when ``True``.
    timeout_seconds : float, default=60.0
        Network timeout for opening the source URL.

    Returns
    -------
    DownloadResult
        Download, existing-file, or manual-download result with provenance.

    Raises
    ------
    CorpusDownloadError
        If the request fails or the downloaded content is not a PDF.
    ValueError
        If ``timeout_seconds`` is not positive.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if source.download_url is None:
        return DownloadResult(
            source_id=source.id,
            status="manual-download-required",
            path=None,
            sha256=None,
            size_bytes=None,
            landing_page_url=str(source.landing_page_url),
            download_url=None,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / source.filename
    if destination.exists() and not overwrite:
        return _existing_result(source, destination)

    partial_path = destination.with_suffix(".pdf.part")
    request = Request(str(source.download_url), headers={"User-Agent": USER_AGENT})
    digest = sha256()
    size_bytes = 0
    first_bytes = b""
    try:
        with (
            urlopen(request, timeout=timeout_seconds) as response,
            partial_path.open("wb") as output_file,
        ):
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                if not first_bytes:
                    first_bytes = chunk[:5]
                digest.update(chunk)
                size_bytes += len(chunk)
                output_file.write(chunk)
        if first_bytes != b"%PDF-":
            raise CorpusDownloadError(f"source {source.id} did not return a PDF file")
        actual_sha256 = digest.hexdigest()
        if (
            source.expected_sha256 is not None
            and actual_sha256 != source.expected_sha256
        ):
            raise CorpusDownloadError(
                f"source {source.id} checksum did not match the catalog"
            )
        partial_path.replace(destination)
    except (HTTPError, URLError, OSError, CorpusDownloadError) as error:
        partial_path.unlink(missing_ok=True)
        if isinstance(error, CorpusDownloadError):
            raise
        raise CorpusDownloadError(
            f"failed to download source {source.id}: {error}"
        ) from error

    return DownloadResult(
        source_id=source.id,
        status="downloaded",
        path=destination.as_posix(),
        sha256=actual_sha256,
        size_bytes=size_bytes,
        landing_page_url=str(source.landing_page_url),
        download_url=str(source.download_url),
    )


def write_download_receipt(
    catalog: CorpusCatalog,
    results: tuple[DownloadResult, ...],
    output_dir: Path,
) -> Path:
    """Write local provenance and checksums for one download run.

    Parameters
    ----------
    catalog : CorpusCatalog
        Catalog used for the run.
    results : tuple of DownloadResult
        Per-source outcomes.
    output_dir : pathlib.Path
        Local corpus directory receiving the receipt.

    Returns
    -------
    pathlib.Path
        Path to the generated JSON receipt.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / "download_receipt.json"
    receipt = {
        "corpus_id": catalog.corpus_id,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "results": [asdict(result) for result in results],
    }
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt_path


def _existing_result(source: CorpusSource, destination: Path) -> DownloadResult:
    """Build a checksum result for an existing local PDF.

    Parameters
    ----------
    source : CorpusSource
        Source metadata for the local file.
    destination : pathlib.Path
        Existing local PDF path.

    Returns
    -------
    DownloadResult
        Existing-file result with its current checksum and size.

    Raises
    ------
    CorpusDownloadError
        If the existing file does not have a PDF signature.
    """
    content = destination.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise CorpusDownloadError(
            f"existing source {source.id} is not a valid PDF file"
        )
    actual_sha256 = sha256(content).hexdigest()
    if source.expected_sha256 is not None and actual_sha256 != source.expected_sha256:
        raise CorpusDownloadError(
            f"existing source {source.id} checksum did not match the catalog"
        )
    return DownloadResult(
        source_id=source.id,
        status="existing",
        path=destination.as_posix(),
        sha256=actual_sha256,
        size_bytes=len(content),
        landing_page_url=str(source.landing_page_url),
        download_url=(
            str(source.download_url) if source.download_url is not None else None
        ),
    )


def _print_catalog(catalog: CorpusCatalog) -> None:
    """Print source download and redistribution status.

    Parameters
    ----------
    catalog : CorpusCatalog
        Catalog to display.
    """
    for source in catalog.sources:
        download_mode = "automatic" if source.download_url else "manual"
        print(
            f"{source.id}\t{source.language}\t{download_mode}\t"
            f"{source.license.redistribution}\t{source.title}"
        )


def main() -> None:
    """List sources or download the selected public PDF corpus."""
    args = parse_args()
    catalog = load_catalog(args.catalog)
    if args.list_sources:
        _print_catalog(catalog)
        return
    selected_sources = select_sources(
        catalog,
        args.source_ids,
        args.download_all,
    )
    output_dir = args.output_dir or catalog.default_output_dir
    results = tuple(
        download_source(source, output_dir, overwrite=args.overwrite)
        for source in selected_sources
    )
    receipt_path = write_download_receipt(catalog, results, output_dir)
    for result in results:
        print(json.dumps(asdict(result), ensure_ascii=False))
    print(f"receipt={receipt_path.as_posix()}")


if __name__ == "__main__":
    main()
