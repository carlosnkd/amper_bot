"""Response schemas for the health/system router.

Written to be compatible with both pydantic v1 and v2 (no version-specific
config blocks); concrete examples live in the route's ``responses`` metadata.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str = Field(default="ok", description="Overall service status.")


class PingResponse(BaseModel):
    """Payload returned by ``GET /ping``."""

    pong: bool = Field(default=True, description="Always true when the app is alive.")
