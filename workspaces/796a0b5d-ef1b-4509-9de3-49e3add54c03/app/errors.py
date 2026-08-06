"""Standard JSON error envelope used by every endpoint.

    {"error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = ["ApiError", "error_envelope", "RATE_LIMIT_EXCEEDED"]

RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


def error_envelope(code: str, message: str, **details: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


class ApiError(Exception):
    """Exception carrying an HTTP status plus the standard error envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = dict(headers or {})

    def to_body(self) -> Dict[str, Any]:
        return error_envelope(self.code, self.message)
