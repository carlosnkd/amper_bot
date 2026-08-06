"""Auth context resolution.

Extremely small stand-in for the real auth layer: a bearer token of the form
``Bearer user:<id>`` (or an ``X-User-Id`` header) populates ``request.auth``.
Anything else leaves the request anonymous, which is what makes the limiter
fall back to IP keying.
"""

from __future__ import annotations

from typing import Optional

from app.http import Request

__all__ = ["authenticate"]

_TOKEN_USERS = {}


def authenticate(request: Request) -> Optional[dict]:
    """Attach ``request.auth`` when credentials are present; return it."""
    if request.auth:
        return request.auth

    user_id = request.headers.get("x-user-id")
    if not user_id:
        authorization = request.headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            if token.startswith("user:"):
                user_id = token[5:].strip()
            elif token in _TOKEN_USERS:
                user_id = _TOKEN_USERS[token]

    if user_id:
        request.auth = {"user_id": str(user_id)}
        return request.auth

    request.auth = None
    return None
