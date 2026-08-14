"""Write privacy-safe structured events for local evaluation runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field


class EvaluationEvent(BaseModel):
    """Represent one structured evaluation lifecycle event."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    level: str = Field(min_length=1)
    service: str = "evaluation"
    run_id: str = Field(min_length=1)
    event: str = Field(min_length=1)
    status: str = Field(min_length=1)
    duration_ms: float | None = Field(default=None, ge=0.0)
    case_count: int | None = Field(default=None, ge=0)
    detail: str | None = None


class JsonlEventWriter:
    """Append evaluation events without logging questions or document text."""

    def __init__(self, path: str | Path, run_id: str) -> None:
        """Create a writer for one evaluation run.

        Parameters
        ----------
        path : str or pathlib.Path
            JSONL event destination.
        run_id : str
            Stable identifier shared by every event.
        """
        self._path = Path(path)
        self._run_id = run_id
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        event: str,
        status: str,
        duration_ms: float | None = None,
        case_count: int | None = None,
        detail: str | None = None,
    ) -> None:
        """Append one privacy-safe structured event.

        Parameters
        ----------
        event : str
            Stable event name.
        status : str
            Lifecycle status such as ``started`` or ``success``.
        duration_ms : float or None, default=None
            Optional measured duration.
        case_count : int or None, default=None
            Optional number of evaluated cases.
        detail : str or None, default=None
            Optional non-sensitive configuration detail.
        """
        payload = EvaluationEvent(
            timestamp=datetime.now(UTC),
            level="INFO",
            run_id=self._run_id,
            event=event,
            status=status,
            duration_ms=duration_ms,
            case_count=case_count,
            detail=detail,
        )
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(payload.model_dump_json() + "\n")


class TimedEvaluationEvent:
    """Measure and write one evaluation suite completion event."""

    def __init__(
        self,
        writer: JsonlEventWriter,
        event: str,
        case_count: int,
    ) -> None:
        """Store an event writer and suite metadata."""
        self._writer = writer
        self._event = event
        self._case_count = case_count
        self._started_at = 0.0

    def __enter__(self) -> TimedEvaluationEvent:
        """Record the suite start and begin duration measurement."""
        self._started_at = perf_counter()
        self._writer.write(self._event, "started", case_count=self._case_count)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Record success or typed failure without source content."""
        duration_ms = (perf_counter() - self._started_at) * 1_000
        self._writer.write(
            self._event,
            "success" if exc_type is None else "failed",
            duration_ms=duration_ms,
            case_count=self._case_count,
            detail=None if exc_type is None else exc_type.__name__,
        )
