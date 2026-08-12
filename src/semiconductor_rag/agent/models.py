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
    answer: GroundedAnswer
    retrieval_attempts: int = Field(ge=1)
    search_queries: tuple[str, ...] = Field(min_length=1)
    search_modes: tuple[SearchMode, ...] = Field(min_length=1)
    termination_reason: AgentTerminationReason
    trace: tuple[AgentTraceEvent, ...] = Field(min_length=1)
