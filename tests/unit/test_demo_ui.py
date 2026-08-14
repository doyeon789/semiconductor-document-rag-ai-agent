"""Unit tests for the Streamlit demo client and response presentation."""

from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from streamlit.testing.v1 import AppTest

from apps.ui.client import ApiResult, RagApiClient, RagApiError
from apps.ui.presentation import build_demo_result


class StubResponse:
    """Provide the context-manager surface returned by ``urlopen``."""

    def __init__(self, payload: dict[str, object]) -> None:
        """Serialize one JSON response body.

        Parameters
        ----------
        payload : dict[str, object]
            Object returned from ``read`` as UTF-8 JSON.
        """
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> StubResponse:
        """Return this response from a context manager.

        Returns
        -------
        StubResponse
            Active response instance.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Leave the response context without suppressing exceptions.

        Parameters
        ----------
        exc_type : type[BaseException] or None
            Exception class raised inside the context.
        exc_value : BaseException or None
            Exception instance raised inside the context.
        traceback : object or None
            Associated traceback object.
        """

    def read(self) -> bytes:
        """Return the serialized response body.

        Returns
        -------
        bytes
            UTF-8 JSON body.
        """
        return self._body


def test_api_client_calls_agent_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send normalized question and limits to the Agent endpoint."""
    captured_request: Request | None = None

    def fake_urlopen(request: Request, timeout: float) -> StubResponse:
        """Capture one outgoing request and return a valid Agent response.

        Parameters
        ----------
        request : urllib.request.Request
            Outgoing Agent request.
        timeout : float
            Configured client timeout.

        Returns
        -------
        StubResponse
            Minimal valid response.
        """
        nonlocal captured_request
        captured_request = request
        assert timeout == 70.0
        return StubResponse({"question": "산화 공정"})

    monkeypatch.setattr("apps.ui.client.urlopen", fake_urlopen)
    result = RagApiClient("http://localhost:8000/").ask(
        "  산화 공정  ",
        agentic=True,
        top_k=5,
        max_claims=2,
    )

    assert result.endpoint == "/v1/agent/answers"
    assert captured_request is not None
    assert captured_request.full_url.endswith("/v1/agent/answers")
    assert captured_request.get_method() == "POST"
    request_body = captured_request.data
    assert isinstance(request_body, bytes)
    assert json.loads(request_body) == {
        "question": "산화 공정",
        "top_k": 5,
        "max_claims": 2,
    }


def test_api_client_explains_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert a low-level connection error into a user-facing message."""

    def fail_urlopen(request: Request, timeout: float) -> StubResponse:
        """Raise a representative connection error.

        Parameters
        ----------
        request : urllib.request.Request
            Unused outgoing request.
        timeout : float
            Unused configured timeout.

        Raises
        ------
        urllib.error.URLError
            Always raised to simulate an offline API.
        """
        raise URLError("connection refused")

    monkeypatch.setattr("apps.ui.client.urlopen", fail_urlopen)

    with pytest.raises(RagApiError, match="API 서버에 연결"):
        RagApiClient("http://localhost:8000").check_health()


def test_api_client_exposes_http_error_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Show FastAPI validation details when a request is rejected."""

    def fail_urlopen(request: Request, timeout: float) -> StubResponse:
        """Raise one JSON HTTP error response.

        Parameters
        ----------
        request : urllib.request.Request
            Unused outgoing request.
        timeout : float
            Unused configured timeout.

        Raises
        ------
        urllib.error.HTTPError
            Always raised with a readable API detail.
        """
        body = BytesIO(json.dumps({"detail": "invalid question"}).encode("utf-8"))
        raise HTTPError(request.full_url, 422, "Unprocessable", Message(), body)

    monkeypatch.setattr("apps.ui.client.urlopen", fail_urlopen)

    with pytest.raises(RagApiError, match="invalid question"):
        RagApiClient("http://localhost:8000").ask(
            "질문",
            agentic=False,
            top_k=5,
            max_claims=1,
        )


def test_api_client_builds_cited_pdf_page_url() -> None:
    """Link a Citation to the browser's one-based PDF page fragment."""
    client = RagApiClient("http://localhost:8000/")

    assert client.document_pdf_url("SEMI-8P-RAG-KO", 8) == (
        "http://localhost:8000/v1/documents/SEMI-8P-RAG-KO/pdf#page=8"
    )


def test_build_demo_result_normalizes_agent_payload() -> None:
    """Flatten nested Agent answer, Citation, and trajectory fields."""
    payload: dict[str, object] = {
        "question": "산화 공정은 무엇인가?",
        "answer": {
            "answer": "산화막을 형성한다.",
            "abstained": False,
            "abstention_reason": None,
            "citations": [
                {
                    "document_id": "SEMI-8P-RAG-KO",
                    "document_title": "반도체 8대 제조 공정",
                    "page_number": 8,
                    "quote": "산화 공정은 산화막을 형성한다.",
                }
            ],
        },
        "termination_reason": "ANSWER_VALIDATED",
        "retrieval_attempts": 1,
        "step_count": 7,
        "search_modes": ["bm25"],
        "tool_errors": [],
        "trace": [
            {
                "sequence": 1,
                "name": "question.classified",
                "mode": None,
                "detail": "DOCUMENT_QUERY",
            }
        ],
    }

    result = build_demo_result(
        ApiResult(endpoint="/v1/agent/answers", payload=payload, elapsed_ms=25.0),
        agentic=True,
    )

    assert result.answer == "산화막을 형성한다."
    assert result.citations[0].page_number == 8
    assert result.search_modes == ("bm25",)
    assert result.trace[0].name == "question.classified"
    assert result.elapsed_ms == 25.0


def test_build_demo_result_normalizes_standard_abstention() -> None:
    """Present a normal evidence-insufficient response without trace fields."""
    payload: dict[str, object] = {
        "question": "문서에 없는 질문",
        "answer": None,
        "abstained": True,
        "abstention_reason": {"message": "근거를 찾지 못했습니다."},
        "citations": [],
        "termination_reason": "EVIDENCE_INSUFFICIENT",
    }

    result = build_demo_result(
        ApiResult(endpoint="/v1/answers", payload=payload, elapsed_ms=12.0),
        agentic=False,
    )

    assert result.abstained is True
    assert result.abstention_message == "근거를 찾지 못했습니다."
    assert result.trace == ()


def test_streamlit_demo_renders_initial_state() -> None:
    """Render all initial controls without a Streamlit runtime exception."""
    app_path = Path(__file__).parents[2] / "apps" / "ui" / "main.py"
    app = AppTest.from_file(app_path).run(timeout=15)

    assert not app.exception
    assert len(app.text_area) == 1
    assert len(app.button) == 4
    assert len(app.sidebar.radio) == 1
    assert len(app.sidebar.slider) == 2
