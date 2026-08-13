"""Validated public contracts for one bounded Agentic RAG execution."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from semiconductor_rag.answering import GroundedAnswer
from semiconductor_rag.retrieval import SearchMode


class AgentTerminationReason(StrEnum):
    """Describe why the bounded retrieval agent stopped."""

    ANSWER_VALIDATED = "ANSWER_VALIDATED"
    RETRIEVAL_LIMIT_REACHED = "RETRIEVAL_LIMIT_REACHED"
    ANSWER_VALIDATION_FAILED = "ANSWER_VALIDATION_FAILED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    STEP_LIMIT_REACHED = "STEP_LIMIT_REACHED"
    TOOL_ERROR = "TOOL_ERROR"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"


class AgentQuestionClass(StrEnum):
    """Describe the safety classification applied before tool use."""

    DOCUMENT_QUERY = "DOCUMENT_QUERY"
    PROMPT_INJECTION = "PROMPT_INJECTION"


class AgentTraceEvent(BaseModel):
    """Record one reconstructable state transition without source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    name: str = Field(min_length=1)
    query: str | None = None
    mode: SearchMode | None = None
    detail: str | None = None


class AgentRun(BaseModel):
    """Return the final answer and bounded retrieval trajectory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: UUID
    question: str = Field(min_length=1)
    question_class: AgentQuestionClass
    answer: GroundedAnswer
    step_count: int = Field(ge=1)
    retrieval_attempts: int = Field(ge=0)
    search_queries: tuple[str, ...]
    search_modes: tuple[SearchMode, ...]
    tool_errors: tuple[str, ...]
    repair_attempts: int = Field(ge=0)
    termination_reason: AgentTerminationReason
    trace: tuple[AgentTraceEvent, ...] = Field(min_length=1)
