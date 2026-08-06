"""Global middleware: request logging and a simple in-process rate limiter.

Both honour ``Settings.public_paths`` so that ``GET /health`` is never
throttled or blocked -- an orchestrator probe that gets a 429 would cause a
pod to be killed exactly when the service is under load.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status and duration for every non-probe request."""

    def __init__(self, app, settings: Settings | None = None) -> None:
        super().__init__(app)
        self.settings = settings or get_settings()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        if not self.settings.is_public_path(request.url.path):
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %s (%.2f ms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client rate limiter with a public-path skip list."""

    def __init__(self, app, settings: Settings | None = None) -> None:
        super().__init__(app)
        self.settings = settings or get_settings()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _client_key(self, request: Request) -> str:
        if request.client and request.client.host:
            return request.client.host
        return "anonymous"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = self.settings
        # Probes and docs are never rate limited.
        if not settings.rate_limit_enabled or settings.is_public_path(
            request.url.path
        ):
            return await call_next(request)

        now = time.monotonic()
        window = settings.rate_limit_window_seconds
        bucket = self._hits[self._client_key(request)]
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) >= settings.rate_limit_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded."},
                headers={"Retry-After": str(window)},
            )

        bucket.append(now)
        return await call_next(request)
