"""Convert API payloads into stable Streamlit presentation models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.ui.client import ApiResult


class CitationView(BaseModel):
    """Describe one source shown below the demo answer."""

    model_config = ConfigDict(extra="ignore")

    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1)


class TraceEventView(BaseModel):
    """Describe one compact Agent state transition."""

    model_config = ConfigDict(extra="ignore")

    sequence: int = Field(ge=1)
    name: str = Field(min_length=1)
    mode: str | None = None
    detail: str | None = None


class DemoResult(BaseModel):
    """Normalize standard and Agentic answer responses for one UI renderer."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    answer: str | None
    abstained: bool
    abstention_message: str | None
    citations: tuple[CitationView, ...]
    termination_reason: str
    elapsed_ms: float = Field(ge=0)
    retrieval_attempts: int | None = Field(default=None, ge=0)
    step_count: int | None = Field(default=None, ge=1)
    search_modes: tuple[str, ...] = ()
    tool_errors: tuple[str, ...] = ()
    trace: tuple[TraceEventView, ...] = ()


def build_demo_result(result: ApiResult, *, agentic: bool) -> DemoResult:
    """Normalize an answer API payload for display.

    Parameters
    ----------
    result : ApiResult
        Decoded API response and client-observed latency.
    agentic : bool
        Whether the response came from the Agent endpoint.

    Returns
    -------
    DemoResult
        Stable answer, Citation, and optional trajectory fields.

    Raises
    ------
    ValueError
        If required answer fields are missing or malformed.
    """
    payload = result.payload
    answer_payload = _require_mapping(payload.get("answer")) if agentic else payload
    abstention_reason = answer_payload.get("abstention_reason")
    abstention_message = None
    if isinstance(abstention_reason, dict):
        message = abstention_reason.get("message")
        abstention_message = message if isinstance(message, str) else None
    citations = tuple(
        CitationView.model_validate(citation)
        for citation in _require_sequence(answer_payload.get("citations", []))
    )
    trace = tuple(
        TraceEventView.model_validate(event)
        for event in _require_sequence(payload.get("trace", []))
    )
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("API response is missing a valid question")
    answer = answer_payload.get("answer")
    if answer is not None and not isinstance(answer, str):
        raise ValueError("API response contains an invalid answer")
    return DemoResult(
        question=question,
        answer=answer,
        abstained=bool(answer_payload.get("abstained")),
        abstention_message=abstention_message,
        citations=citations,
        termination_reason=str(payload.get("termination_reason", "UNKNOWN")),
        elapsed_ms=result.elapsed_ms,
        retrieval_attempts=_optional_int(payload.get("retrieval_attempts")),
        step_count=_optional_int(payload.get("step_count")),
        search_modes=tuple(str(mode) for mode in payload.get("search_modes", [])),
        tool_errors=tuple(str(error) for error in payload.get("tool_errors", [])),
        trace=trace,
    )


def _require_mapping(value: Any) -> dict[str, Any]:
    """Require a JSON object value.

    Parameters
    ----------
    value : Any
        Decoded JSON value.

    Returns
    -------
    dict[str, Any]
        Validated object value.

    Raises
    ------
    ValueError
        If the value is not an object.
    """
    if not isinstance(value, dict):
        raise ValueError("API response is missing an answer object")
    return value


def _require_sequence(value: Any) -> list[Any]:
    """Require a JSON array value.

    Parameters
    ----------
    value : Any
        Decoded JSON value.

    Returns
    -------
    list[Any]
        Validated array value.

    Raises
    ------
    ValueError
        If the value is not an array.
    """
    if not isinstance(value, list):
        raise ValueError("API response contains an invalid list field")
    return value


def _optional_int(value: Any) -> int | None:
    """Return an integer value without accepting booleans.

    Parameters
    ----------
    value : Any
        Decoded JSON value.

    Returns
    -------
    int or None
        Integer value when present.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None
