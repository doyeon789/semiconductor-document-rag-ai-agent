"""Run reproducible retrieval baselines over one verified local corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from semiconductor_rag.corpus import (
    DEFAULT_CATALOG_PATH,
    LoadedCorpus,
    load_corpus,
)
from semiconductor_rag.evaluation import (
    RetrievalDataset,
    evaluate_retrieval,
    load_retrieval_dataset,
)
from semiconductor_rag.ingestion import build_page_chunks, extract_pdf
from semiconductor_rag.retrieval import (
    FastEmbedder,
    FastEmbedReranker,
    LocalSearchService,
    SearchMode,
)

DEFAULT_DATASET_PATH = Path("data/evaluation/ai_security_retrieval_dev.json")
DEFAULT_OUTPUT_ROOT = Path("output/evaluation")
LEGACY_PDF_PATH = Path(
    "output/pdf/semiconductor_8_processes_chunking_guide_ko_v1_3.pdf"
)


def parse_args() -> argparse.Namespace:
    """Parse corpus, dataset, strategy, and output arguments.

    Returns
    -------
    argparse.Namespace
        Parsed catalog, PDF directory, dataset, modes, and output options.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--legacy-pdf", type=Path, default=LEGACY_PDF_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[mode.value for mode in SearchMode],
        default=[mode.value for mode in SearchMode],
    )
    return parser.parse_args()


def main() -> None:
    """Load the requested dataset, run retrieval modes, and write JSON."""
    args = parse_args()
    if args.top_k < 1:
        raise ValueError("top_k must be positive")
    dataset = load_retrieval_dataset(args.dataset)
    modes = tuple(SearchMode(mode) for mode in args.modes)
    if dataset.corpus_id is not None:
        corpus = load_corpus(args.catalog, args.pdf_dir)
        validate_dataset_against_corpus(dataset, corpus)
        search_service = LocalSearchService(
            corpus.chunks,
            FastEmbedder(),
            FastEmbedReranker(),
            sources_by_version=corpus.sources_by_version,
        )
        corpus_summary = _summarize_corpus(corpus)
    else:
        search_service, corpus_summary = _build_legacy_search_service(
            dataset,
            args.legacy_pdf,
        )

    answerable_cases = [case for case in dataset.cases if case.answerable]
    evaluations = [
        evaluate_retrieval(search_service, answerable_cases, mode, args.top_k)
        for mode in modes
    ]
    report = {
        "schema_version": 2,
        "dataset_id": dataset.dataset_id,
        "split": dataset.split,
        **corpus_summary,
        "embedding_model": search_service.embedding_model_name,
        "reranker_model": search_service.reranker_model_name,
        "evaluations": [
            evaluation.model_dump(mode="json") for evaluation in evaluations
        ],
    }
    output_path = args.output or DEFAULT_OUTPUT_ROOT / f"{dataset.dataset_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "dataset_id": dataset.dataset_id,
                "output": output_path.as_posix(),
                "evaluations": [
                    evaluation.model_dump(mode="json", exclude={"cases"})
                    for evaluation in evaluations
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def validate_dataset_against_corpus(
    dataset: RetrievalDataset,
    corpus: LoadedCorpus,
) -> None:
    """Validate every multi-document gold page against loaded PDFs.

    Parameters
    ----------
    dataset : RetrievalDataset
        Versioned multi-document evaluation questions.
    corpus : LoadedCorpus
        Verified local documents and searchable chunks.

    Raises
    ------
    ValueError
        If corpus identity, document identity, page bounds, exclusions, or
        searchable content do not match the dataset annotations.
    """
    if dataset.corpus_id != corpus.corpus_id:
        raise ValueError(
            f"dataset corpus {dataset.corpus_id} does not match {corpus.corpus_id}"
        )
    documents_by_id = {
        document.source.document_id: document for document in corpus.documents
    }
    unknown_dataset_documents = set(dataset.document_ids).difference(documents_by_id)
    if unknown_dataset_documents:
        unknown_text = ", ".join(sorted(unknown_dataset_documents))
        raise ValueError(f"dataset references unknown documents: {unknown_text}")

    for case in dataset.cases:
        for evidence in case.gold:
            if evidence.document_id not in dataset.document_ids:
                raise ValueError(
                    f"case {case.id} references undeclared document "
                    f"{evidence.document_id}"
                )
            document = documents_by_id[evidence.document_id]
            searchable_pages = {chunk.page_start for chunk in document.chunks}
            for page_number in evidence.pages:
                if page_number > document.page_count:
                    raise ValueError(
                        f"case {case.id} page {page_number} exceeds "
                        f"{evidence.document_id} page count"
                    )
                if page_number in document.excluded_pages:
                    raise ValueError(
                        f"case {case.id} uses excluded page {page_number} "
                        f"from {evidence.document_id}"
                    )
                if page_number not in searchable_pages:
                    raise ValueError(
                        f"case {case.id} page {page_number} has no searchable "
                        f"content in {evidence.document_id}"
                    )


def _summarize_corpus(corpus: LoadedCorpus) -> dict[str, object]:
    """Build reproducibility metadata for one loaded corpus.

    Parameters
    ----------
    corpus : LoadedCorpus
        Verified multi-document corpus used by the evaluation.

    Returns
    -------
    dict[str, object]
        Corpus identity, document counts, page counts, and chunk count.
    """
    page_count = sum(document.page_count for document in corpus.documents)
    excluded_page_count = sum(
        len(document.excluded_pages) for document in corpus.documents
    )
    return {
        "corpus_id": corpus.corpus_id,
        "document_count": len(corpus.documents),
        "page_count": page_count,
        "excluded_page_count": excluded_page_count,
        "searchable_page_count": page_count - excluded_page_count,
        "chunk_count": len(corpus.chunks),
    }


def _build_legacy_search_service(
    dataset: RetrievalDataset,
    pdf_path: Path,
) -> tuple[LocalSearchService, dict[str, object]]:
    """Build the retained single-document regression search service.

    Parameters
    ----------
    dataset : RetrievalDataset
        Legacy dataset with one document identifier and version.
    pdf_path : pathlib.Path
        Local legacy PDF used only for regression checks.

    Returns
    -------
    LocalSearchService
        Search service built from the legacy PDF.
    dict[str, object]
        Legacy document metadata included in the JSON report.

    Raises
    ------
    ValueError
        If the legacy dataset omits its document identity or version.
    """
    if not dataset.document_id.strip() or not dataset.document_version.strip():
        raise ValueError("legacy datasets require document_id and document_version")
    version_id = uuid5(
        NAMESPACE_URL,
        f"{dataset.document_id}:{dataset.document_version}",
    )
    pages = extract_pdf(pdf_path, version_id)
    excluded_pages = set(dataset.excluded_corpus_pages)
    searchable_pages = tuple(
        page for page in pages if page.page.page_number not in excluded_pages
    )
    chunks = build_page_chunks(searchable_pages, version_id)
    service = LocalSearchService(
        chunks,
        FastEmbedder(),
        FastEmbedReranker(),
    )
    return service, {
        "document_id": dataset.document_id,
        "document_version": dataset.document_version,
        "page_count": len(pages),
        "excluded_page_count": len(excluded_pages),
        "searchable_page_count": len(searchable_pages),
        "chunk_count": len(chunks),
    }


if __name__ == "__main__":
    main()
