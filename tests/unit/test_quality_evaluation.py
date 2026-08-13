"""Unit tests for answer, Citation, Agent, and report evaluation."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from semiconductor_rag.agent import (
    AgentQuestionClass,
    AgentRun,
    AgentTerminationReason,
    AgentTraceEvent,
)
from semiconductor_rag.answering import (
    EvidencePack,
    build_evidence_pack,
    build_grounded_answer,
)
from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.evaluation import (
    EvaluationManifest,
    JsonlEventWriter,
    RetrievalCase,
    evaluate_quality,
    evaluate_retrieval,
    write_evaluation_report,
)
from semiconductor_rag.retrieval import SearchHit, SearchMode

VERSION_ID = UUID("77777777-7777-4777-8777-777777777777")


class QualityTestAgent:
    """Return prebuilt Agent runs keyed by question."""

    def __init__(self, runs: dict[str, AgentRun]) -> None:
        """Store deterministic run fixtures."""
        self._runs = runs

    def run(
        self,
        question: str,
        top_k: int = 5,
        max_claims: int = 1,
        max_retrieval_attempts: int = 2,
    ) -> AgentRun:
        """Return the fixture for one question."""
        return self._runs[question]


class QualityTestSearchService:
    """Return one deterministic relevant page for report tests."""

    def prepare(self, mode: SearchMode) -> None:
        """Provide a no-op preparation hook."""

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.BM25,
        top_k: int = 5,
    ) -> tuple[SearchHit, ...]:
        """Return the fixed answer page."""
        return (_make_hit(8, "산화 공정은 절연막을 형성한다."),)


def _make_hit(page: int, text: str) -> SearchHit:
    """Create one stable page-local search hit."""
    chunk = Chunk(
        chunk_id=UUID(int=page),
        version_id=VERSION_ID,
        chunk_type=ChunkType.TEXT,
        text=text,
        page_start=page,
        page_end=page,
        token_count=len(text.split()),
        content_hash=sha256(text.encode()).hexdigest(),
    )
    return SearchHit(chunk=chunk, score=1.0)


def _make_run(
    question: str,
    text: str | None,
    page: int = 8,
    termination: AgentTerminationReason = AgentTerminationReason.ANSWER_VALIDATED,
    modes: tuple[SearchMode, ...] = (SearchMode.BM25,),
) -> AgentRun:
    """Create one complete answer or abstention trajectory."""
    if text is None:
        answer = build_grounded_answer(EvidencePack(query=question, blocks=()))
    else:
        evidence = build_evidence_pack(
            question,
            (_make_hit(page, text),),
            document_id="doc-1",
            document_title="공정 안내서",
        )
        answer = build_grounded_answer(evidence)
    events = (
        AgentTraceEvent(sequence=1, name="question.classified"),
        AgentTraceEvent(
            sequence=2,
            name="agent.completed" if text is not None else "agent.abstained",
        ),
    )
    return AgentRun(
        trace_id=uuid4(),
        question=question,
        question_class=AgentQuestionClass.DOCUMENT_QUERY,
        answer=answer,
        step_count=2,
        retrieval_attempts=len(modes),
        search_queries=tuple(question for _ in modes),
        search_modes=modes,
        tool_errors=(),
        repair_attempts=0,
        termination_reason=termination,
        trace=events,
    )


def test_evaluate_quality_combines_answer_citation_and_abstention_metrics() -> None:
    """Score independently verified answers and correct abstention together."""
    answer_question = "산화 공정은 무엇인가?"
    missing_question = "양자컴퓨터 큐비트 오류정정 방식은?"
    agent = QualityTestAgent(
        {
            answer_question: _make_run(
                answer_question,
                "산화 공정은 절연막을 형성한다.",
            ),
            missing_question: _make_run(
                missing_question,
                None,
                termination=AgentTerminationReason.RETRIEVAL_LIMIT_REACHED,
                modes=(SearchMode.BM25, SearchMode.RERANK),
            ),
        }
    )
    cases = [
        RetrievalCase(
            id="Q1",
            query=answer_question,
            expected_pages=[8],
            required_facts=["절연막"],
            expected_search_modes=[SearchMode.BM25],
            expected_events=["question.classified"],
        ),
        RetrievalCase(
            id="Q2",
            query=missing_question,
            answerable=False,
            intent="unanswerable",
            expected_search_modes=[SearchMode.BM25, SearchMode.RERANK],
            expected_events=["agent.abstained"],
            expected_termination_reason=AgentTerminationReason.RETRIEVAL_LIMIT_REACHED,
        ),
    ]

    result = evaluate_quality(
        agent,
        cases,
        {8: "산화 공정은 절연막을 형성한다."},
    )

    assert result.pass_rate == 1.0
    assert result.required_fact_coverage == 1.0
    assert result.citation_precision == 1.0
    assert result.page_match_accuracy == 1.0
    assert result.abstention_precision == 1.0
    assert result.abstention_recall == 1.0
    assert result.unsafe_answer_rate == 0.0
    assert result.trajectory_accuracy == 1.0


def test_evaluate_quality_classifies_wrong_page_failure() -> None:
    """Expose a valid quote from the wrong gold page as a diagnosable failure."""
    question = "산화 공정은 무엇인가?"
    agent = QualityTestAgent(
        {question: _make_run(question, "산화 공정은 절연막을 형성한다.", page=9)}
    )
    case = RetrievalCase(id="Q1", query=question, expected_pages=[8])

    result = evaluate_quality(
        agent,
        [case],
        {9: "산화 공정은 절연막을 형성한다."},
    )

    assert result.pass_rate == 0.0
    assert result.cases[0].failure_reasons == ["wrong_page"]


def test_write_evaluation_report_creates_reproducible_artifacts(
    tmp_path: Path,
) -> None:
    """Write the documented report structure and privacy-safe event log."""
    question = "산화 공정은 무엇인가?"
    case = RetrievalCase(
        id="Q1",
        query=question,
        expected_pages=[8],
        required_facts=["절연막"],
    )
    quality = evaluate_quality(
        QualityTestAgent(
            {question: _make_run(question, "산화 공정은 절연막을 형성한다.")}
        ),
        [case],
        {8: "산화 공정은 절연막을 형성한다."},
    )
    retrieval = evaluate_retrieval(
        QualityTestSearchService(),
        [case],
        SearchMode.RERANK,
    )
    manifest = EvaluationManifest(
        run_id="run-test",
        git_sha="1234567890abcdef",
        dataset_id="eval-v1",
        document_id="doc-1",
        document_version="1",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        embedding_version="embedding-v1",
        reranker_version="reranker-v1",
        configuration={"top_k": 5},
        budgets={"llm_tokens": 0},
    )

    artifacts = write_evaluation_report(
        tmp_path / "run-test",
        manifest,
        {SearchMode.RERANK: retrieval},
        quality,
    )
    event_writer = JsonlEventWriter(artifacts.output_dir / "events.jsonl", "run-test")
    event_writer.write("evaluation.run", "success", case_count=1)

    assert artifacts.manifest.is_file()
    assert artifacts.aggregate_metrics.is_file()
    assert artifacts.slice_metrics.is_file()
    assert artifacts.retrieval_results.is_file()
    assert artifacts.answer_results.is_file()
    assert artifacts.agent_trajectories.is_file()
    assert artifacts.failures.read_text(encoding="utf-8").endswith(
        "실패 사례가 없습니다.\n"
    )
    event = json.loads(
        (artifacts.output_dir / "events.jsonl").read_text(encoding="utf-8")
    )
    assert event["run_id"] == "run-test"
    assert "question" not in event


def test_numeric_accuracy_requires_exact_number_and_unit() -> None:
    """Treat a changed numeric value as an answer-quality failure."""
    question = "온도는?"
    agent = QualityTestAgent({question: _make_run(question, "공정 온도는 900 ℃이다.")})
    case = RetrievalCase(
        id="Q1",
        query=question,
        expected_pages=[8],
        required_numbers=["950 ℃"],
    )

    result = evaluate_quality(agent, [case], {8: "공정 온도는 900 ℃이다."})

    assert result.numeric_accuracy == 0.0
    assert "numeric_mismatch" in result.cases[0].failure_reasons
