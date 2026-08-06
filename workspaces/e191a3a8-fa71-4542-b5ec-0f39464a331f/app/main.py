"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.rate_limit import RateLimitMiddleware
from app.routers import health, items
from app.security import ApiKeyAuthMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_tags=[
            {"name": "system", "description": "Public health and liveness endpoints."},
            {"name": "items", "description": "Authenticated business endpoints."},
        ],
    )

    # Outermost middleware runs first; both consult Settings.public_paths so
    # /ping (and /health, /docs, /openapi.json) stay reachable without auth.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(ApiKeyAuthMiddleware, settings=settings)

    # No prefix: the final paths are exactly /health and /ping.
    app.include_router(health.router)
    app.include_router(items.router)

    return app


app = create_app()
