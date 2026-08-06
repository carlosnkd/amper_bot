"""Global API-key authentication middleware.

Every route is protected by default; the paths listed in
``Settings.public_paths`` (which includes ``/ping``) are exempt.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings

API_KEY_HEADER = "X-API-Key"


def is_public_path(path: str, settings: Settings) -> bool:
    """Return True when ``path`` must be served without credentials."""
    normalised = path if path == "/" else path.rstrip("/")
    return normalised in settings.public_paths


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self.settings.auth_enabled or is_public_path(request.url.path, self.settings):
            return await call_next(request)

        provided = request.headers.get(API_KEY_HEADER)
        if not provided or provided != self.settings.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API key"},
            )
        return await call_next(request)
