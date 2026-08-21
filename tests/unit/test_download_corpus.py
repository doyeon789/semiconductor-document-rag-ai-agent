"""Unit tests for public PDF corpus catalog and download behavior."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from scripts.download_corpus import (
    CorpusCatalog,
    CorpusDownloadError,
    CorpusSource,
    download_source,
    load_catalog,
    select_sources,
)

CATALOG_PATH = Path("data/corpus/sources.yaml")


class StubResponse:
    """Provide the context manager and read surface used by ``urlopen``."""

    def __init__(self, content: bytes) -> None:
        """Store response content and initialize its read position.

        Parameters
        ----------
        content : bytes
            Bytes returned across response reads.
        """
        self._content = content
        self._position = 0

    def __enter__(self) -> StubResponse:
        """Return this response for a context-managed request.

        Returns
        -------
        StubResponse
            Active response stub.
        """
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        """Leave the response context without suppressing exceptions."""

    def read(self, size: int = -1) -> bytes:
        """Read at most ``size`` bytes from the stored response.

        Parameters
        ----------
        size : int, default=-1
            Maximum bytes to return, or all remaining bytes when negative.

        Returns
        -------
        bytes
            Next response segment.
        """
        if size < 0:
            size = len(self._content) - self._position
        start = self._position
        self._position = min(len(self._content), self._position + size)
        return self._content[start : self._position]


def _catalog() -> CorpusCatalog:
    """Load the committed public corpus catalog.

    Returns
    -------
    CorpusCatalog
        Validated repository catalog.
    """
    return load_catalog(CATALOG_PATH)


def _source(source_id: str) -> CorpusSource:
    """Find one source in the committed catalog.

    Parameters
    ----------
    source_id : str
        Catalog identifier to find.

    Returns
    -------
    CorpusSource
        Matching source metadata.
    """
    return next(source for source in _catalog().sources if source.id == source_id)


def test_catalog_records_multilingual_sources_and_license_status() -> None:
    """Keep Korean and English official sources with explicit usage terms."""
    catalog = _catalog()

    assert len(catalog.sources) == 6
    assert {source.language for source in catalog.sources} == {"ko-KR", "en-US"}
    assert all(source.license.notice for source in catalog.sources)
    assert all(source.download_url is not None for source in catalog.sources)
    assert all(source.expected_sha256 is not None for source in catalog.sources)
    assert sum(source.expected_page_count or 0 for source in catalog.sources) == 773
    assert sum(len(source.excluded_pages) for source in catalog.sources) == 16
    assert all(
        str(source.landing_page_url).startswith("https://")
        for source in catalog.sources
    )
    assert all(
        source.license.reference_url is not None
        for source in catalog.sources
        if source.license.identifier != "NOASSERTION"
    )


def test_select_sources_preserves_catalog_order_and_rejects_unknown_ids() -> None:
    """Return explicit sources deterministically and fail unknown requests."""
    catalog = _catalog()

    selected = select_sources(
        catalog,
        ["owasp-genai-llm-top-10-2026", "nist-ai-rmf-1-0"],
        download_all=False,
    )

    assert [source.id for source in selected] == [
        "nist-ai-rmf-1-0",
        "owasp-genai-llm-top-10-2026",
    ]
    with pytest.raises(ValueError, match="unknown corpus source ids: missing"):
        select_sources(catalog, ["missing"], download_all=False)


def test_download_source_writes_verified_pdf_and_checksum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Download only PDF bytes and report their local integrity hash."""
    content = b"%PDF-1.7\npublic test document"

    def fake_urlopen(request: object, timeout: float) -> StubResponse:
        """Return deterministic PDF bytes for the downloader.

        Parameters
        ----------
        request : object
            Request created by the downloader.
        timeout : float
            Positive timeout passed by the downloader.

        Returns
        -------
        StubResponse
            Context-managed byte response.
        """
        assert request is not None
        assert timeout == 60.0
        return StubResponse(content)

    monkeypatch.setattr("scripts.download_corpus.urlopen", fake_urlopen)
    source = _source("nist-ai-rmf-1-0").model_copy(
        update={"expected_sha256": sha256(content).hexdigest()}
    )

    result = download_source(source, tmp_path)

    destination = tmp_path / source.filename
    assert destination.read_bytes() == content
    assert result.status == "downloaded"
    assert result.sha256 == sha256(content).hexdigest()
    assert result.size_bytes == len(content)
    assert result.download_url == str(source.download_url)


def test_download_source_rejects_non_pdf_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Delete partial output when an official URL does not return a PDF."""

    def fake_urlopen(request: object, timeout: float) -> StubResponse:
        """Return an HTML response for PDF signature validation.

        Parameters
        ----------
        request : object
            Request created by the downloader.
        timeout : float
            Positive timeout passed by the downloader.

        Returns
        -------
        StubResponse
            Context-managed HTML byte response.
        """
        return StubResponse(b"<html>not a pdf</html>")

    monkeypatch.setattr("scripts.download_corpus.urlopen", fake_urlopen)
    source = _source("nist-ai-rmf-1-0")

    with pytest.raises(CorpusDownloadError, match="did not return a PDF"):
        download_source(source, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_source_rejects_changed_official_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject PDF bytes whose checksum differs from the fixed source version."""

    def fake_urlopen(request: object, timeout: float) -> StubResponse:
        """Return a changed PDF for checksum validation.

        Parameters
        ----------
        request : object
            Request created by the downloader.
        timeout : float
            Positive timeout passed by the downloader.

        Returns
        -------
        StubResponse
            Context-managed changed PDF response.
        """
        return StubResponse(b"%PDF-1.7\nchanged document")

    monkeypatch.setattr("scripts.download_corpus.urlopen", fake_urlopen)
    source = _source("nist-ai-rmf-1-0")

    with pytest.raises(CorpusDownloadError, match="checksum did not match"):
        download_source(source, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_source_without_direct_url_requires_manual_download(
    tmp_path: Path,
) -> None:
    """Keep catalog sources without a stable direct URL outside automation."""
    source = _source("kisa-ai-security-guide-corrected-2026").model_copy(
        update={"download_url": None}
    )

    result = download_source(source, tmp_path)

    assert result.status == "manual-download-required"
    assert result.path is None
    assert list(tmp_path.iterdir()) == []
