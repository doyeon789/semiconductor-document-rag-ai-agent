"""Run local BM25, dense, and hybrid retrieval baselines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from semiconductor_rag.evaluation import evaluate_retrieval, load_retrieval_dataset
from semiconductor_rag.ingestion import build_page_chunks, extract_pdf
from semiconductor_rag.retrieval import FastEmbedder, LocalSearchService, SearchMode

DEFAULT_PDF_PATH = Path(
    "output/pdf/semiconductor_8_processes_chunking_guide_ko_v1_3.pdf"
)
DEFAULT_DATASET_PATH = Path("data/evaluation/retrieval_cases.json")
DEFAULT_OUTPUT_PATH = Path("output/evaluation/retrieval_baseline.json")


def parse_args() -> argparse.Namespace:
    """Parse local baseline input and output paths.

    Returns
    -------
    argparse.Namespace
        Parsed PDF, dataset, output, and top-k arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    """Build the local corpus, evaluate all modes, and write a JSON report."""
    args = parse_args()
    dataset = load_retrieval_dataset(args.dataset)
    version_id = uuid5(
        NAMESPACE_URL,
        f"{dataset.document_id}:{dataset.document_version}",
    )
    pages = extract_pdf(args.pdf, version_id)
    excluded_pages = set(dataset.excluded_corpus_pages)
    searchable_pages = tuple(
        page for page in pages if page.page.page_number not in excluded_pages
    )
    chunks = build_page_chunks(searchable_pages, version_id)
    search_service = LocalSearchService(chunks, FastEmbedder())
    evaluations = [
        evaluate_retrieval(search_service, dataset.cases, mode, args.top_k)
        for mode in SearchMode
    ]
    report = {
        "dataset_id": dataset.dataset_id,
        "document_id": dataset.document_id,
        "document_version": dataset.document_version,
        "chunk_count": len(chunks),
        "excluded_corpus_pages": dataset.excluded_corpus_pages,
        "embedding_model": search_service.embedding_model_name,
        "evaluations": [
            evaluation.model_dump(mode="json") for evaluation in evaluations
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
