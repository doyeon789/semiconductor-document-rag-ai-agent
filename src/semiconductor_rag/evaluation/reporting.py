"""Generate reproducible JSON, JSONL, and Markdown evaluation artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.evaluation.quality import AnswerCaseResult, QualityEvaluation
from semiconductor_rag.evaluation.retrieval import RetrievalEvaluation
from semiconductor_rag.retrieval import SearchMode


class EvaluationManifest(BaseModel):
    """Capture versions and budgets required to reproduce one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    git_sha: str = Field(min_length=7)
    dataset_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    reranker_version: str | None
    llm_model: str | None = None
    prompt_version: str | None = None
    configuration: dict[str, object]
    budgets: dict[str, int | float]


class ReleaseGates(BaseModel):
    """Record each MVP gate independently instead of hiding failures."""

    model_config = ConfigDict(extra="forbid")

    retrieval_page_hit: bool
    retrieval_recall: bool
    retrieval_mrr: bool
    citation_precision: bool
    citation_coverage: bool
    page_match_accuracy: bool
    quote_match_rate: bool
    abstention_precision: bool
    abstention_recall: bool
    unsafe_answer_rate: bool
    trajectory_accuracy: bool
    max_step_violations: bool
    passed: bool


class EvaluationArtifacts(BaseModel):
    """Return all files written for one evaluation run."""

    model_config = ConfigDict(extra="forbid")

    output_dir: Path
    manifest: Path
    aggregate_metrics: Path
    slice_metrics: Path
    retrieval_results: Path
    answer_results: Path
    agent_trajectories: Path
    failures: Path
    summary: Path


def build_release_gates(
    retrieval: Mapping[SearchMode, RetrievalEvaluation],
    quality: QualityEvaluation,
) -> ReleaseGates:
    """Evaluate documented MVP thresholds against one complete run.

    Parameters
    ----------
    retrieval : collections.abc.Mapping[SearchMode, RetrievalEvaluation]
        Retrieval results keyed by strategy.
    quality : QualityEvaluation
        Answer, Citation, abstention, and trajectory metrics.

    Returns
    -------
    ReleaseGates
        Individual gate outcomes and their conjunction.
    """
    preferred = retrieval.get(SearchMode.RERANK) or max(
        retrieval.values(), key=lambda evaluation: evaluation.page_hit_at_k
    )
    values = {
        "retrieval_page_hit": preferred.page_hit_at_k >= 0.80,
        "retrieval_recall": preferred.recall_at_k >= 0.75,
        "retrieval_mrr": preferred.mrr >= 0.60,
        "citation_precision": quality.citation_precision >= 0.90,
        "citation_coverage": quality.citation_coverage >= 0.90,
        "page_match_accuracy": quality.page_match_accuracy >= 0.90,
        "quote_match_rate": quality.quote_match_rate >= 0.95,
        "abstention_precision": quality.abstention_precision >= 0.80,
        "abstention_recall": quality.abstention_recall >= 0.85,
        "unsafe_answer_rate": quality.unsafe_answer_rate <= 0.05,
        "trajectory_accuracy": quality.trajectory_accuracy >= 1.0,
        "max_step_violations": quality.max_step_violation_count == 0,
    }
    return ReleaseGates(**values, passed=all(values.values()))


def build_slice_metrics(
    cases: Sequence[AnswerCaseResult],
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Aggregate quality metrics by language and intent.

    Parameters
    ----------
    cases : collections.abc.Sequence[AnswerCaseResult]
        Per-case answer and trajectory results.

    Returns
    -------
    dict
        Slice metrics grouped by each supported case attribute.
    """
    slices: dict[str, dict[str, dict[str, float | int]]] = {}
    for attribute in ("language", "intent"):
        grouped: dict[str, list[AnswerCaseResult]] = defaultdict(list)
        for case in cases:
            grouped[str(getattr(case, attribute))].append(case)
        slices[attribute] = {
            value: {
                "case_count": len(group),
                "pass_rate": mean(float(case.passed) for case in group),
                "page_match_accuracy": mean(case.page_match_accuracy for case in group),
                "trajectory_accuracy": mean(
                    float(case.trajectory_correct) for case in group
                ),
            }
            for value, group in sorted(grouped.items())
        }
    return slices


def write_evaluation_report(
    output_dir: str | Path,
    manifest: EvaluationManifest,
    retrieval: Mapping[SearchMode, RetrievalEvaluation],
    quality: QualityEvaluation,
) -> EvaluationArtifacts:
    """Write the complete reproducible evaluation artifact set.

    Parameters
    ----------
    output_dir : str or pathlib.Path
        Empty or existing run directory.
    manifest : EvaluationManifest
        Reproduction metadata and budgets.
    retrieval : collections.abc.Mapping[SearchMode, RetrievalEvaluation]
        Per-mode retrieval evaluation results.
    quality : QualityEvaluation
        Answer and Agent quality results.

    Returns
    -------
    EvaluationArtifacts
        Paths of every generated artifact.
    """
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = EvaluationArtifacts(
        output_dir=directory,
        manifest=directory / "manifest.json",
        aggregate_metrics=directory / "aggregate_metrics.json",
        slice_metrics=directory / "slice_metrics.json",
        retrieval_results=directory / "retrieval_results.jsonl",
        answer_results=directory / "answer_results.jsonl",
        agent_trajectories=directory / "agent_trajectories.jsonl",
        failures=directory / "failures.md",
        summary=directory / "summary.md",
    )
    gates = build_release_gates(retrieval, quality)
    aggregate = {
        "retrieval": {
            mode.value: evaluation.model_dump(mode="json", exclude={"cases"})
            for mode, evaluation in retrieval.items()
        },
        "quality": quality.model_dump(mode="json", exclude={"cases"}),
        "release_gates": gates.model_dump(mode="json"),
    }
    _write_json(paths.manifest, manifest.model_dump(mode="json"))
    _write_json(paths.aggregate_metrics, aggregate)
    _write_json(paths.slice_metrics, build_slice_metrics(quality.cases))
    _write_jsonl(
        paths.retrieval_results,
        (
            {"mode": mode.value, **case.model_dump(mode="json")}
            for mode, evaluation in retrieval.items()
            for case in evaluation.cases
        ),
    )
    _write_jsonl(
        paths.answer_results,
        (case.model_dump(mode="json") for case in quality.cases),
    )
    _write_jsonl(
        paths.agent_trajectories,
        (
            {
                "id": case.id,
                "termination_reason": case.termination_reason.value,
                "search_modes": [mode.value for mode in case.search_modes],
                "trace_events": case.trace_events,
                "retrieval_attempts": case.retrieval_attempts,
                "step_count": case.step_count,
                "tool_error_count": case.tool_error_count,
                "trajectory_correct": case.trajectory_correct,
            }
            for case in quality.cases
        ),
    )
    paths.failures.write_text(_render_failures(quality.cases), encoding="utf-8")
    paths.summary.write_text(
        _render_summary(manifest, retrieval, quality, gates),
        encoding="utf-8",
    )
    return paths


def _write_json(path: Path, payload: object) -> None:
    """Write stable pretty-printed UTF-8 JSON."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, payloads: Iterable[object]) -> None:
    """Write an iterable of JSON objects as UTF-8 JSONL."""
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _render_failures(cases: Sequence[AnswerCaseResult]) -> str:
    """Render failed case identifiers and diagnostic categories."""
    failed = [case for case in cases if not case.passed]
    lines = ["# Evaluation Failures", ""]
    if not failed:
        return "\n".join((*lines, "실패 사례가 없습니다.", ""))
    for case in failed:
        reasons = ", ".join(case.failure_reasons)
        modes = " → ".join(mode.value for mode in case.search_modes) or "none"
        lines.extend(
            (
                f"## {case.id}",
                "",
                f"- 분류: `{case.intent}` / `{case.language}`",
                f"- 실패 유형: `{reasons}`",
                f"- 검색 경로: `{modes}`",
                f"- 종료 이유: `{case.termination_reason.value}`",
                "",
            )
        )
    return "\n".join(lines)


def _render_summary(
    manifest: EvaluationManifest,
    retrieval: Mapping[SearchMode, RetrievalEvaluation],
    quality: QualityEvaluation,
    gates: ReleaseGates,
) -> str:
    """Render a compact human-readable evaluation summary."""
    lines = [
        f"# Evaluation Run {manifest.run_id}",
        "",
        f"- Git SHA: `{manifest.git_sha}`",
        f"- Dataset: `{manifest.dataset_id}`",
        f"- MVP Gate: `{'PASS' if gates.passed else 'FAIL'}`",
        "",
        "## Retrieval",
        "",
        "| Mode | Page Hit@K | Recall@K | MRR | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {mode.value} | {result.page_hit_at_k:.3f} | "
        f"{result.recall_at_k:.3f} | {result.mrr:.3f} | "
        f"{result.p95_latency_ms:.1f} |"
        for mode, result in retrieval.items()
    )
    lines.extend(
        (
            "",
            "## Answer, Citation, Agent",
            "",
            f"- Case pass rate: `{quality.pass_rate:.3f}`",
            f"- Required fact coverage: `{quality.required_fact_coverage:.3f}`",
            f"- Citation precision: `{quality.citation_precision:.3f}`",
            f"- Page match accuracy: `{quality.page_match_accuracy:.3f}`",
            f"- Quote match rate: `{quality.quote_match_rate:.3f}`",
            f"- Abstention recall: `{quality.abstention_recall:.3f}`",
            f"- Unsafe answer rate: `{quality.unsafe_answer_rate:.3f}`",
            f"- Trajectory accuracy: `{quality.trajectory_accuracy:.3f}`",
            f"- Average retrieval attempts: `{quality.average_retrieval_attempts:.3f}`",
            f"- Mean answer latency: `{quality.mean_latency_ms:.1f} ms`",
            "",
        )
    )
    return "\n".join(lines)
