"""Pydantic response contracts for the public API."""

from typing import Optional

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    """Payload returned by GET /."""

    message: str = Field(..., examples=["Hello, World!"])


class ItemResponse(BaseModel):
    """Payload returned by GET /items/{item_id}."""

    item_id: int = Field(..., examples=[1])
    q: Optional[str] = Field(default=None, examples=["search term"])


class HealthResponse(BaseModel):
    """Payload returned by GET /health."""

    status: str = Field(..., examples=["ok"])
    version: str = Field(..., examples=["1.0.0"])


class ErrorResponse(BaseModel):
    """Consistent error envelope used by every exception handler."""

    detail: object
    status_code: int
