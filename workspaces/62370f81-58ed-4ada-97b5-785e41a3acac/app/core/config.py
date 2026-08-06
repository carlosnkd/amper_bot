"""Application settings.

Kept dependency-light on purpose: the health endpoint must be importable and
serveable even when optional infrastructure (DB, cache) is unavailable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import FrozenSet


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration."""

    project_name: str = os.getenv("PROJECT_NAME", "Example Service")
    #: Version prefix applied to *business* routers only. /health is mounted
    #: at the root and deliberately does not inherit this prefix.
    api_v1_prefix: str = os.getenv("API_V1_PREFIX", "/api/v1")
    api_key: str = os.getenv("API_KEY", "local-dev-key")
    api_key_header: str = "X-API-Key"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    rate_limit_enabled: bool = _env_bool("RATE_LIMIT_ENABLED", True)
    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    #: Paths that must always be reachable without credentials and without
    #: being rate limited: orchestrator/load-balancer probes and API docs.
    public_paths: FrozenSet[str] = field(
        default_factory=lambda: frozenset(
            {"/health", "/docs", "/redoc", "/openapi.json"}
        )
    )

    def is_public_path(self, path: str) -> bool:
        """Return True when *path* is exempt from auth and rate limiting."""
        normalized = path.rstrip("/") or "/"
        return normalized in {p.rstrip("/") or "/" for p in self.public_paths}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
