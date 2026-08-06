"""Very small in-process fixed-window rate limiter.

Shares the public-path whitelist with the auth middleware so liveness probes
(``/ping``) are never throttled.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings
from app.security import is_public_path


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def _client_key(self, request: Request) -> str:
        if request.client and request.client.host:
            return request.client.host
        return "anonymous"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self.settings.rate_limit_enabled or is_public_path(
            request.url.path, self.settings
        ):
            return await call_next(request)

        now = time.monotonic()
        window = self.settings.rate_limit_window_seconds
        key = self._client_key(request)
        recent = [ts for ts in self._hits[key] if now - ts < window]

        if len(recent) >= self.settings.rate_limit_requests:
            self._hits[key] = recent
            return JSONResponse(status_code=429, content={"detail": "Too many requests"})

        recent.append(now)
        self._hits[key] = recent
        return await call_next(request)
