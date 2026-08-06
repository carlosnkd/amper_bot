"""Health / system router.

All routes here are public (see ``Settings.public_paths``): they carry no
authentication and are never rate limited, so orchestrators can probe them.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.schemas.health import HealthResponse, PingResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service health check",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def health() -> HealthResponse:
    """Return a static health payload. Does not probe dependencies."""
    return HealthResponse(status="ok")


@router.get(
    "/ping",
    response_model=PingResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    responses={200: {"content": {"application/json": {"example": {"pong": True}}}}},
)
async def ping() -> PingResponse:
    """Unauthenticated liveness probe.

    Always returns ``{"pong": true}`` with HTTP 200. It touches no database,
    cache, or downstream service.
    """
    return PingResponse(pong=True)
