"""Rate limit decorator for individual endpoints (currently POST /chat only).

Usage::

    @router.route("POST", "/chat")
    @rate_limit_chat(limiter_provider=lambda: app.chat_limiter)
    def chat(request): ...

The decorator resolves the limit key, calls the limiter and either short
circuits with a 429 (before any downstream/model call) or lets the handler run
and decorates the successful response with the X-RateLimit-* headers.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, Optional, Tuple

from app.errors import RATE_LIMIT_EXCEEDED, error_envelope
from app.http import Request, Response, json_response

__all__ = ["resolve_limit_key", "client_ip", "rate_limit_chat"]

_PRIVATE_PREFIXES = ("10.", "192.168.", "172.16.", "127.", "::1", "fd", "fc")


def client_ip(request: Request, settings=None) -> str:
    """Best-effort client IP.

    When proxy headers are trusted, use the first entry of X-Forwarded-For that
    is not itself a configured trusted proxy; otherwise fall back to the socket
    peer address.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    if getattr(settings, "trust_proxy_headers", False):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            trusted = set(getattr(settings, "trusted_proxies", ()) or ())
            candidates = [part.strip() for part in forwarded.split(",")]
            for candidate in candidates:
                if candidate and candidate not in trusted:
                    return candidate
    return request.remote_addr or "unknown"


def resolve_limit_key(request: Request, settings=None) -> Tuple[str, str, str]:
    """Return ``(key, key_type, identifier)`` for this request."""
    user_id = request.user_id
    if user_id:
        return f"chat:user:{user_id}", "user", user_id
    ip = client_ip(request, settings)
    return f"chat:ip:{ip}", "ip", ip


def rate_limit_chat(
    limiter_provider: Callable[[], object],
    endpoint: str = "/chat",
    settings_provider: Optional[Callable[[], object]] = None,
):
    """Decorator factory wiring a handler to the chat limiter."""

    def decorator(handler: Callable[[Request], object]) -> Callable[[Request], object]:
        @wraps(handler)
        def wrapper(request: Request):
            limiter = limiter_provider()
            settings = (
                settings_provider() if settings_provider else getattr(limiter, "settings", None)
            )

            if limiter is None or not getattr(limiter, "enabled", False):
                return handler(request)

            key, key_type, identifier = resolve_limit_key(request, settings)
            decision = limiter.check(
                key, key_type=key_type, identifier=identifier, endpoint=endpoint
            )
            request.state["rate_limit"] = decision

            if not decision.allowed:
                # Short circuit: the downstream model is never called.
                response = json_response(
                    error_envelope(RATE_LIMIT_EXCEEDED, decision.message()),
                    429,
                )
                response.headers.update(decision.headers())
                return response

            result = handler(request)
            response = result if isinstance(result, Response) else _to_response(result)
            response.headers.update(decision.headers())
            return response

        return wrapper

    return decorator


def _to_response(result) -> Response:
    if isinstance(result, tuple):
        if len(result) == 2:
            return json_response(result[0], result[1])
        if len(result) == 3:
            return json_response(result[0], result[1], result[2])
        raise TypeError("handler tuple must be (body, status[, headers])")
    return json_response(result)
