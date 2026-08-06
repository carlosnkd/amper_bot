"""Liveness probe router.

Mounted at the application root as ``GET /health`` (no version prefix) so
load balancers, Docker HEALTHCHECK and Kubernetes ``livenessProbe`` can target
a stable path.

This is a *shallow* liveness check: it answers "is this process able to serve
HTTP?" and deliberately touches no database, cache or downstream service, so
it keeps returning 200 while dependencies are degraded. A deep readiness
check, if ever needed, belongs on a separate ``/ready`` endpoint.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Body returned by the liveness probe."""

    status: Literal["ok"] = Field(
        default="ok",
        description="Always 'ok' when the process can serve HTTP.",
        examples=["ok"],
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description=(
        "Shallow liveness check. Returns 200 with {\"status\": \"ok\"} whenever "
        "the process can serve HTTP. Does not check the database or any other "
        "downstream dependency, and requires no authentication."
    ),
    response_description="The service is alive.",
)
async def health() -> HealthResponse:
    """Return a static OK payload. No params, no dependencies, no I/O."""
    return HealthResponse(status="ok")
