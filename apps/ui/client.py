"""Small standard-library HTTP client for the Streamlit demo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RagApiError(RuntimeError):
    """Describe an API connection or response failure safe for UI display."""


@dataclass(frozen=True, slots=True)
class ApiResult:
    """Carry one decoded API response with client-observed latency."""

    endpoint: str
    payload: dict[str, Any]
    elapsed_ms: float


class RagApiClient:
    """Call the local FastAPI RAG endpoints without UI dependencies."""

    def __init__(self, base_url: str, timeout_seconds: float = 70.0) -> None:
        """Store a normalized API address and request timeout.

        Parameters
        ----------
        base_url : str
            FastAPI origin such as ``http://127.0.0.1:8000``.
        timeout_seconds : float, default=70.0
            Maximum wait for one API request.

        Raises
        ------
        ValueError
            If the URL is blank or the timeout is not positive.
        """
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("base_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = normalized_url
        self._timeout_seconds = timeout_seconds

    @property
    def base_url(self) -> str:
        """Return the normalized FastAPI origin.

        Returns
        -------
        str
            API origin without a trailing slash.
        """
        return self._base_url

    def check_health(self) -> ApiResult:
        """Request the liveness endpoint.

        Returns
        -------
        ApiResult
            Decoded liveness response and round-trip latency.

        Raises
        ------
        RagApiError
            If the server cannot be reached or returns invalid JSON.
        """
        return self._request("GET", "/health/live")

    def ask(
        self,
        question: str,
        *,
        agentic: bool,
        top_k: int,
        max_claims: int,
    ) -> ApiResult:
        """Send one grounded-answer request.

        Parameters
        ----------
        question : str
            User question sent to the document RAG API.
        agentic : bool
            Whether to use the bounded LangGraph execution endpoint.
        top_k : int
            Maximum evidence candidates requested from retrieval.
        max_claims : int
            Maximum page-grounded claims returned to the UI.

        Returns
        -------
        ApiResult
            Decoded answer payload and round-trip latency.

        Raises
        ------
        ValueError
            If the question is blank or a numeric limit is not positive.
        RagApiError
            If the server cannot be reached or rejects the request.
        """
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be blank")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if max_claims < 1:
            raise ValueError("max_claims must be positive")
        endpoint = "/v1/agent/answers" if agentic else "/v1/answers"
        return self._request(
            "POST",
            endpoint,
            {
                "question": normalized_question,
                "top_k": top_k,
                "max_claims": max_claims,
            },
        )

    def document_pdf_url(self, document_id: str, page_number: int) -> str:
        """Build a browser URL for one cited PDF page.

        Parameters
        ----------
        document_id : str
            Stable source document identifier.
        page_number : int
            One-based PDF page number.

        Returns
        -------
        str
            FastAPI PDF endpoint with a browser page fragment.

        Raises
        ------
        ValueError
            If the identifier is blank or the page number is not positive.
        """
        normalized_id = document_id.strip()
        if not normalized_id:
            raise ValueError("document_id must not be blank")
        if page_number < 1:
            raise ValueError("page_number must be positive")
        return f"{self._base_url}/v1/documents/{normalized_id}/pdf#page={page_number}"

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> ApiResult:
        """Execute one JSON request and normalize transport errors.

        Parameters
        ----------
        method : str
            HTTP method accepted by the target endpoint.
        endpoint : str
            Absolute API path beginning with ``/``.
        payload : dict[str, Any] or None, default=None
            Optional JSON request body.

        Returns
        -------
        ApiResult
            Decoded object response and elapsed time.

        Raises
        ------
        RagApiError
            If the transport fails, the status is unsuccessful, or the body
            is not a JSON object.
        """
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{endpoint}",
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        started_at = perf_counter()
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _read_http_error(exc)
            raise RagApiError(
                f"API 요청이 실패했습니다 ({exc.code}): {detail}"
            ) from exc
        except URLError as exc:
            raise RagApiError(
                "API 서버에 연결할 수 없습니다. FastAPI 실행 상태를 확인해 주세요."
            ) from exc
        elapsed_ms = (perf_counter() - started_at) * 1_000
        try:
            decoded = json.loads(response_body)
        except JSONDecodeError as exc:
            raise RagApiError("API가 올바른 JSON을 반환하지 않았습니다.") from exc
        if not isinstance(decoded, dict):
            raise RagApiError("API 응답은 JSON 객체여야 합니다.")
        return ApiResult(endpoint=endpoint, payload=decoded, elapsed_ms=elapsed_ms)


def _read_http_error(error: HTTPError) -> str:
    """Extract a concise detail message from one HTTP error.

    Parameters
    ----------
    error : urllib.error.HTTPError
        Failed HTTP response raised by ``urlopen``.

    Returns
    -------
    str
        API detail text or the HTTP reason as a fallback.
    """
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return str(error.reason)
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(error.reason)
