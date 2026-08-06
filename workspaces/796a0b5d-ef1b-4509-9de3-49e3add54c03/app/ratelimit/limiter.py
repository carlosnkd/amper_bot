"""Limiter facade: policy + fail-open behaviour + observability."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from app import metrics
from app.ratelimit.store import (
    RateLimitResult,
    RateLimitStore,
    RateLimitStoreError,
    build_store,
)

__all__ = ["ChatRateLimiter", "RateLimitDecision"]

logger = logging.getLogger("app.ratelimit")

#: don't spam the logs when Redis is down - one warning per this many seconds
INFRA_ERROR_LOG_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class RateLimitDecision:
    """What the endpoint layer needs to know after a limiter check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_at: int
    key: Optional[str] = None
    key_type: Optional[str] = None
    identifier: Optional[str] = None
    enforced: bool = True
    failed_open: bool = False

    def headers(self) -> Dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, self.retry_after))
        return headers

    def message(self) -> str:
        seconds = max(1, self.retry_after)
        return f"Too many messages. Try again in {seconds} seconds."


class ChatRateLimiter:
    """Applies the configured chat policy to a resolved limit key."""

    def __init__(
        self,
        store: Optional[RateLimitStore] = None,
        settings=None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        self.settings = settings
        self._clock: Callable[[], float] = clock or time.time
        self.store = store if store is not None else build_store(settings, clock=clock)
        self._last_infra_log_at: float = 0.0
        self._suppressed_infra_errors: int = 0
        self._log_lock = threading.Lock()

    # -- policy ---------------------------------------------------------
    @property
    def limit(self) -> int:
        return self.settings.rate_limit_chat_max_requests

    @property
    def window_seconds(self) -> int:
        return self.settings.rate_limit_chat_window_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.settings.rate_limit_enabled)

    # -- main entry point -----------------------------------------------
    def check(
        self,
        key: str,
        key_type: str = "user",
        identifier: str = "",
        endpoint: str = "/chat",
    ) -> RateLimitDecision:
        now = float(self._clock())

        if not self.enabled:
            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=self.limit,
                retry_after=0,
                reset_at=int(now) + self.window_seconds,
                key=key,
                key_type=key_type,
                identifier=identifier,
                enforced=False,
            )

        try:
            result: RateLimitResult = self.store.check_and_consume(
                key, self.limit, self.window_seconds
            )
        except Exception as exc:  # noqa: BLE001 - fail open on ANY infra error
            self._log_infra_error(exc, endpoint=endpoint)
            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=self.limit,
                retry_after=0,
                reset_at=int(now) + self.window_seconds,
                key=key,
                key_type=key_type,
                identifier=identifier,
                enforced=True,
                failed_open=True,
            )

        decision = RateLimitDecision(
            allowed=result.allowed,
            limit=result.limit,
            remaining=result.remaining,
            retry_after=result.retry_after,
            reset_at=result.reset_at,
            key=key,
            key_type=key_type,
            identifier=identifier,
        )

        if not decision.allowed:
            self._record_rejection(decision, endpoint)

        return decision

    # -- observability ---------------------------------------------------
    def _record_rejection(self, decision: RateLimitDecision, endpoint: str) -> None:
        logger.warning(
            "rate_limit_rejected",
            extra={
                "event": "rate_limit_rejected",
                "endpoint": endpoint,
                "key_type": decision.key_type,
                "identifier": decision.identifier,
                "limit": decision.limit,
                "window_seconds": self.window_seconds,
                "retry_after": decision.retry_after,
                "reset_at": decision.reset_at,
            },
        )
        try:
            metrics.increment(
                metrics.RATE_LIMIT_REJECTIONS_TOTAL,
                labels={
                    "endpoint": endpoint,
                    "key_type": decision.key_type or "unknown",
                },
            )
        except Exception:  # noqa: BLE001 - metrics must never break a request
            logger.debug("rate_limit metric emit failed", exc_info=True)

    def _log_infra_error(self, exc: Exception, endpoint: str) -> None:
        now = float(self._clock())
        should_log = False
        suppressed = 0
        with self._log_lock:
            if now - self._last_infra_log_at >= INFRA_ERROR_LOG_INTERVAL_SECONDS:
                should_log = True
                suppressed = self._suppressed_infra_errors
                self._suppressed_infra_errors = 0
                self._last_infra_log_at = now
            else:
                self._suppressed_infra_errors += 1

        if should_log:
            logger.warning(
                "rate_limit_store_unavailable failing_open=true "
                "endpoint=%s error=%s suppressed_since_last_log=%d",
                endpoint,
                exc,
                suppressed,
                extra={
                    "event": "rate_limit_store_unavailable",
                    "endpoint": endpoint,
                    "error": str(exc),
                    "failing_open": True,
                    "suppressed_since_last_log": suppressed,
                    "store_error": isinstance(exc, RateLimitStoreError),
                },
            )
