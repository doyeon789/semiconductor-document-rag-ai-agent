"""Public RAG evaluation contracts, metrics, and report generation."""

from semiconductor_rag.evaluation.error_analysis import (
    RetrievalErrorAnalysis,
    RetrievalFailureCase,
    RetrievalFailureType,
    analyze_retrieval_failures,
)
from semiconductor_rag.evaluation.observability import (
    EvaluationEvent,
    JsonlEventWriter,
    TimedEvaluationEvent,
)
from semiconductor_rag.evaluation.quality import (
    AnswerCaseResult,
    EvaluationAgent,
    QualityEvaluation,
    evaluate_quality,
)
from semiconductor_rag.evaluation.reporting import (
    EvaluationArtifacts,
    EvaluationManifest,
    ReleaseGates,
    build_release_gates,
    build_slice_metrics,
    write_evaluation_report,
)
from semiconductor_rag.evaluation.retrieval import (
    EvaluationSearchService,
    RetrievalCase,
    RetrievalCaseResult,
    RetrievalDataset,
    RetrievalEvaluation,
    evaluate_retrieval,
    load_retrieval_dataset,
)

__all__ = [
    "AnswerCaseResult",
    "EvaluationAgent",
    "EvaluationArtifacts",
    "EvaluationEvent",
    "EvaluationManifest",
    "EvaluationSearchService",
    "JsonlEventWriter",
    "QualityEvaluation",
    "ReleaseGates",
    "RetrievalCase",
    "RetrievalCaseResult",
    "RetrievalDataset",
    "RetrievalErrorAnalysis",
    "RetrievalEvaluation",
    "RetrievalFailureCase",
    "RetrievalFailureType",
    "TimedEvaluationEvent",
    "analyze_retrieval_failures",
    "build_release_gates",
    "build_slice_metrics",
    "evaluate_quality",
    "evaluate_retrieval",
    "load_retrieval_dataset",
    "write_evaluation_report",
]
