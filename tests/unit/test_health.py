"""Unit tests for the API process liveness contract."""

from fastapi.testclient import TestClient

from apps.api.main import app


def test_live_health_returns_ok() -> None:
    """Return HTTP 200 and a stable body for a live API process."""
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
