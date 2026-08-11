"""Create the HTTP API application and its process health contract."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict


class LiveHealthResponse(BaseModel):
    """Describe a live API process."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


async def get_live_health() -> LiveHealthResponse:
    """Return the API process liveness state.

    Returns
    -------
    LiveHealthResponse
        A response indicating that the process can serve requests.
    """
    return LiveHealthResponse()


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns
    -------
    FastAPI
        Configured HTTP application.
    """
    application = FastAPI(
        title="Semiconductor Document RAG API",
        version="0.1.0",
    )
    application.add_api_route(
        "/health/live",
        get_live_health,
        methods=["GET"],
        response_model=LiveHealthResponse,
        tags=["health"],
    )
    return application


app = create_app()
