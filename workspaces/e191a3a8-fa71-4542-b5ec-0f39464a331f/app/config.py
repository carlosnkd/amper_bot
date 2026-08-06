"""Application settings.

Kept dependency-free (stdlib only) so the app boots in any environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import FrozenSet


def _public_paths() -> FrozenSet[str]:
    """Paths reachable without credentials and without rate limiting.

    `/ping` is a liveness probe and therefore lives here alongside the other
    unauthenticated system/documentation endpoints.
    """
    return frozenset(
        {
            "/ping",
            "/health",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
            "/openapi.json",
        }
    )


@dataclass(frozen=True)
class Settings:
    app_name: str = "Example Service"
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", "dev-secret-key"))
    auth_enabled: bool = field(
        default_factory=lambda: os.getenv("AUTH_ENABLED", "1") not in {"0", "false", "False"}
    )
    rate_limit_enabled: bool = field(
        default_factory=lambda: os.getenv("RATE_LIMIT_ENABLED", "1")
        not in {"0", "false", "False"}
    )
    rate_limit_requests: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    )
    rate_limit_window_seconds: float = field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    )
    public_paths: FrozenSet[str] = field(default_factory=_public_paths)


@lru_cache
def get_settings() -> Settings:
    return Settings()
