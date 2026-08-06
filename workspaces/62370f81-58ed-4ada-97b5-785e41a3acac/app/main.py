"""FastAPI application entrypoint.

Router wiring rules
-------------------
* ``health_router`` is included first, at the **root** path with no prefix and
  with **no** ``dependencies=[...]``, so the final path is exactly ``/health``
  and probes work without an API key.
* Every other router is included under ``settings.api_v1_prefix`` behind the
  ``require_api_key`` dependency.
* The rate limiting and request logging middleware skip ``Settings.public_paths``,
  which contains ``/health``.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from app.api.routers.health import router as health_router
from app.api.routers.items import router as items_router
from app.core.config import Settings, get_settings
from app.core.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.core.security import require_api_key


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.project_name,
        version="1.0.0",
        openapi_tags=[
            {"name": "health", "description": "Liveness and probe endpoints."},
            {"name": "items", "description": "Example business endpoints."},
        ],
    )

    # Middleware. Both implementations exempt settings.public_paths (/health).
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(RequestLoggingMiddleware, settings=settings)

    # --- Public, unversioned, unauthenticated: liveness probe. -------------
    # No prefix and no dependencies => final path is exactly "/health".
    app.include_router(health_router)

    # --- Versioned + authenticated API. ------------------------------------
    app.include_router(
        items_router,
        prefix=settings.api_v1_prefix,
        dependencies=[Depends(require_api_key)],
    )

    return app


app = create_app()
