"""Unit tests for bounded LangGraph retrieval agent routes."""

from collections.abc import Callable
from hashlib import sha256
from uuid import UUID

from semiconductor_rag.agent import (
    AgentTerminationReason,
    RetrievalAgent,
    rewrite_semiconductor_query,
)
from semiconductor_rag.answering import (
    EvidencePack,
    GroundedAnswer,
    build_evidence_pack,
    build_grounded_answer,
)
from semiconductor_rag.domain import Chunk, ChunkType
from semiconductor_rag.retrieval import SearchHit, SearchMode

VERSION_ID = UUID("44444444-4444-4444-8444-444444444444")


class ScriptedAgentTools:
    """Return scenario-specific evidence while recording tool choices."""

    def __init__(
        self,
        search_script: Callable[[str, SearchMode], EvidencePack],
        invalidate_answer: bool = False,
    ) -> None:
        """Store search behavior and optional citation corruption."""
        self._search_script = search_script
        self._invalidate_answer = invalidate_answer
        self.calls: list[tuple[str, SearchMode, int]] = []

    def search_evidence(
        self,
        query: str,
        mode: SearchMode,
        top_k: int,
    ) -> EvidencePack:
        """Return scripted evidence and record selected tool arguments."""
        self.calls.append((query, mode, top_k))
        return self._search_script(query, mode)

    def answer_evidence(
        self,
        evidence: EvidencePack,
        max_claims: int,
    ) -> GroundedAnswer:
        """Build a real answer and optionally corrupt its citation quote."""
        answer = build_grounded_answer(evidence, max_claims=max_claims)
        if not self._invalidate_answer:
            return answer
        invalid_citation = answer.citations[0].model_copy(
            update={"quote": "원문에 없는 문장"}
        )
        return answer.model_copy(update={"citations": (invalid_citation,)})


def _make_evidence(query: str, text: str, page: int = 8) -> EvidencePack:
    """Create one page-grounded evidence pack for an agent scenario."""
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
    return build_evidence_pack(
        query,
        (SearchHit(chunk=chunk, score=0.9),),
        document_id="doc-1",
        document_title="공정 안내서",
    )


def _empty_evidence(query: str) -> EvidencePack:
    """Create an evidence-insufficient tool result."""
    return EvidencePack(query=query, blocks=())


def test_agent_finishes_after_sufficient_first_search() -> None:
    """Use fast BM25 once when its evidence already supports an answer."""
    tools = ScriptedAgentTools(
        lambda query, mode: _make_evidence(query, "산화 공정은 절연막을 형성한다.")
    )

    result = RetrievalAgent(tools).run("산화 공정은 무엇인가?")

    assert result.answer.abstained is False
    assert result.retrieval_attempts == 1
    assert result.search_modes == (SearchMode.BM25,)
    assert result.termination_reason is AgentTerminationReason.ANSWER_VALIDATED
    assert [event.name for event in result.trace] == [
        "tool.search.completed",
        "retrieval.sufficiency_checked",
        "answer.generated",
        "citation.validated",
        "agent.completed",
    ]


def test_agent_rewrites_and_reranks_after_insufficient_search() -> None:
    """Expand a domain alias and retry once with precise reranking."""

    def search_script(query: str, mode: SearchMode) -> EvidencePack:
        """Return ALD evidence only for the reranked expanded query."""
        if mode is SearchMode.RERANK and "ALD" in query:
            return _make_evidence(query, "ALD 공정은 원자층 단위로 박막을 성장시킨다.")
        return _empty_evidence(query)

    tools = ScriptedAgentTools(search_script)

    result = RetrievalAgent(tools).run("원자층 막성장의 특징은?")

    assert result.answer.abstained is False
    assert result.retrieval_attempts == 2
    assert result.search_modes == (SearchMode.BM25, SearchMode.RERANK)
    assert "ALD" in result.search_queries[1]
    assert any(event.name == "query.rewritten" for event in result.trace)
    assert result.termination_reason is AgentTerminationReason.ANSWER_VALIDATED


def test_agent_abstains_at_retrieval_limit() -> None:
    """Stop after the configured attempts instead of entering an open loop."""
    tools = ScriptedAgentTools(lambda query, mode: _empty_evidence(query))

    result = RetrievalAgent(tools).run("문서에 없는 초전도 큐비트 질문")

    assert result.answer.abstained is True
    assert result.retrieval_attempts == 2
    assert result.termination_reason is AgentTerminationReason.RETRIEVAL_LIMIT_REACHED
    assert result.trace[-1].name == "agent.abstained"


def test_agent_blocks_answer_with_invalid_citation() -> None:
    """Replace a quote-mismatched draft with a safe abstention."""
    tools = ScriptedAgentTools(
        lambda query, mode: _make_evidence(query, "산화 공정은 절연막을 형성한다."),
        invalidate_answer=True,
    )

    result = RetrievalAgent(tools).run("산화 공정은 무엇인가?")

    assert result.answer.abstained is True
    assert result.answer.citations == ()
    assert result.termination_reason is AgentTerminationReason.ANSWER_VALIDATION_FAILED


def test_query_rewrite_adds_domain_aliases_once() -> None:
    """Add English aliases without duplicating an alias already in the query."""
    rewrite = rewrite_semiconductor_query("ALD 원자층 증착 조건")

    assert rewrite.rewritten_query.count("ALD") == 1
    assert "atomic layer deposition" in rewrite.added_terms
