"""Application settings, loaded from environment variables.

All rate-limit knobs live here so ops can tune the policy without a code change:

    RATE_LIMIT_ENABLED              (bool, default true)
    RATE_LIMIT_CHAT_MAX_REQUESTS    (positive int, default 10)
    RATE_LIMIT_CHAT_WINDOW_SECONDS  (positive int, default 60)
    REDIS_URL                       (str, optional - in-memory store when unset)
    REDIS_TIMEOUT_SECONDS           (positive float, default 0.25)
    TRUST_PROXY_HEADERS             (bool, default false)
    TRUSTED_PROXIES                 (comma separated IPs, default empty)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

__all__ = [
    "ConfigError",
    "Settings",
    "get_settings",
    "reload_settings",
    "set_settings",
]

_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", "f"}


class ConfigError(ValueError):
    """Raised when an environment variable holds an invalid value."""


def _get(env: Mapping[str, str], name: str) -> Optional[str]:
    raw = env.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _bool_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(
        f"{name} must be a boolean value (got {raw!r}); "
        f"use one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}"
    )


def _positive_int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer (got {raw!r})") from None
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer (got {value})")
    return value


def _positive_float_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number (got {raw!r})") from None
    if value <= 0:
        raise ConfigError(f"{name} must be a positive number (got {value})")
    return value


def _csv_env(env: Mapping[str, str], name: str) -> Tuple[str, ...]:
    raw = _get(env, name)
    if raw is None:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the app configuration."""

    rate_limit_enabled: bool = True
    rate_limit_chat_max_requests: int = 10
    rate_limit_chat_window_seconds: int = 60
    redis_url: Optional[str] = None
    redis_timeout_seconds: float = 0.25
    trust_proxy_headers: bool = False
    trusted_proxies: Tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.rate_limit_chat_max_requests <= 0:
            raise ConfigError("rate_limit_chat_max_requests must be a positive integer")
        if self.rate_limit_chat_window_seconds <= 0:
            raise ConfigError(
                "rate_limit_chat_window_seconds must be a positive integer"
            )
        if self.redis_timeout_seconds <= 0:
            raise ConfigError("redis_timeout_seconds must be a positive number")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            rate_limit_enabled=_bool_env(env, "RATE_LIMIT_ENABLED", True),
            rate_limit_chat_max_requests=_positive_int_env(
                env, "RATE_LIMIT_CHAT_MAX_REQUESTS", 10
            ),
            rate_limit_chat_window_seconds=_positive_int_env(
                env, "RATE_LIMIT_CHAT_WINDOW_SECONDS", 60
            ),
            redis_url=_get(env, "REDIS_URL"),
            redis_timeout_seconds=_positive_float_env(
                env, "REDIS_TIMEOUT_SECONDS", 0.25
            ),
            trust_proxy_headers=_bool_env(env, "TRUST_PROXY_HEADERS", False),
            trusted_proxies=_csv_env(env, "TRUSTED_PROXIES"),
        )


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the process-wide settings, loading them from env on first use."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reload_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Re-read settings from the environment (useful in tests)."""
    global _settings
    _settings = Settings.from_env(env)
    return _settings


def set_settings(settings: Optional[Settings]) -> None:
    """Inject (or clear, with None) the process-wide settings."""
    global _settings
    _settings = settings
