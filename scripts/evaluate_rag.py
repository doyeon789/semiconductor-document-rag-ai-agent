"""Run retrieval, answer, Citation, abstention, and Agent evaluation suites."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from semiconductor_rag.agent import LocalRetrievalAgentTools, RetrievalAgent
from semiconductor_rag.answering import MIN_RERANK_RELEVANCE_SCORE
from semiconductor_rag.evaluation import (
    EvaluationManifest,
    JsonlEventWriter,
    TimedEvaluationEvent,
    evaluate_quality,
    evaluate_retrieval,
    load_retrieval_dataset,
    write_evaluation_report,
)
from semiconductor_rag.ingestion import build_page_chunks, extract_pdf
from semiconductor_rag.retrieval import (
    FastEmbedder,
    FastEmbedReranker,
    LocalSearchService,
    SearchMode,
)

DEFAULT_PDF_PATH = Path(
    "output/pdf/semiconductor_8_processes_chunking_guide_ko_v1_3.pdf"
)
DEFAULT_DATASET_PATH = Path("data/evaluation/rag_cases.json")
DEFAULT_OUTPUT_ROOT = Path("output/evaluation")
DEFAULT_DOCUMENT_TITLE = "반도체 8대 제조 공정: 웨이퍼에서 패키징까지"


def parse_args() -> argparse.Namespace:
    """Parse full evaluation paths, strategies, and limits.

    Returns
    -------
    argparse.Namespace
        Validated command-line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-claims", type=int, default=3)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[mode.value for mode in SearchMode],
        default=[mode.value for mode in SearchMode],
    )
    return parser.parse_args()


def main() -> None:
    """Build the local corpus and generate every evaluation artifact."""
    args = parse_args()
    if args.top_k < 1:
        raise ValueError("top_k must be positive")
    if args.max_claims < 1:
        raise ValueError("max_claims must be positive")

    dataset = load_retrieval_dataset(args.dataset)
    git_sha = _read_git_sha()
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{git_sha[:7]}"
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / run_id
    event_writer = JsonlEventWriter(output_dir / "events.jsonl", run_id)
    event_writer.write(
        "evaluation.run",
        "started",
        case_count=len(dataset.cases),
        detail=f"dataset={dataset.dataset_id}",
    )

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
    search_service = LocalSearchService(
        chunks,
        FastEmbedder(),
        FastEmbedReranker(),
    )
    modes = tuple(SearchMode(mode) for mode in args.modes)
    retrieval_cases = [case for case in dataset.cases if case.answerable]
    retrieval_results = {}
    for mode in modes:
        with TimedEvaluationEvent(
            event_writer,
            f"evaluation.retrieval.{mode.value}",
            len(retrieval_cases),
        ):
            retrieval_results[mode] = evaluate_retrieval(
                search_service,
                retrieval_cases,
                mode,
                args.top_k,
            )

    tools = LocalRetrievalAgentTools(
        search_service,
        document_id=dataset.document_id,
        document_title=DEFAULT_DOCUMENT_TITLE,
    )
    agent = RetrievalAgent(tools)
    page_texts = {
        page.page.page_number: " ".join(element.text for element in page.elements)
        for page in pages
    }
    with TimedEvaluationEvent(
        event_writer,
        "evaluation.quality",
        len(dataset.cases),
    ):
        quality = evaluate_quality(
            agent,
            dataset.cases,
            page_texts,
            top_k=args.top_k,
            max_claims=args.max_claims,
        )

    manifest = EvaluationManifest(
        run_id=run_id,
        git_sha=git_sha,
        dataset_id=dataset.dataset_id,
        document_id=dataset.document_id,
        document_version=dataset.document_version,
        parser_version="pymupdf-native-v1",
        chunker_version="page-aware-v1",
        embedding_version=search_service.embedding_model_name,
        reranker_version=search_service.reranker_model_name,
        llm_model=None,
        prompt_version=None,
        configuration={
            "top_k": args.top_k,
            "max_claims": args.max_claims,
            "modes": [mode.value for mode in modes],
            "excluded_corpus_pages": dataset.excluded_corpus_pages,
            "agent_max_steps": 14,
            "agent_max_retrieval_attempts": 2,
            "agent_tool_timeout_seconds": 45.0,
            "min_rerank_relevance_score": MIN_RERANK_RELEVANCE_SCORE,
        },
        budgets={
            "search_p95_warm_ms": 2_000,
            "answer_p95_ms": 15_000,
            "agent_timeout_ms": 45_000,
            "llm_tokens": 0,
            "llm_cost_usd": 0.0,
        },
    )
    artifacts = write_evaluation_report(
        output_dir,
        manifest,
        retrieval_results,
        quality,
    )
    event_writer.write(
        "evaluation.run",
        "success",
        case_count=len(dataset.cases),
        detail=f"output={artifacts.output_dir.as_posix()}",
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "output_dir": str(artifacts.output_dir),
                "case_count": quality.case_count,
                "pass_rate": quality.pass_rate,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_git_sha() -> str:
    """Return the full Git commit identifier for report reproducibility.

    Returns
    -------
    str
        Current ``HEAD`` commit SHA.

    Raises
    ------
    RuntimeError
        If the repository commit cannot be resolved.
    """
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    git_sha = completed.stdout.strip()
    if completed.returncode != 0 or len(git_sha) < 7:
        raise RuntimeError("unable to resolve the current Git SHA")
    return git_sha


if __name__ == "__main__":
    main()
