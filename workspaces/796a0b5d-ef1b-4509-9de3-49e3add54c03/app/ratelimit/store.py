"""Sliding-window rate limit stores.

Two implementations with identical semantics:

* :class:`RedisRateLimitStore` - atomic Lua script over a sorted set, safe to
  share across processes / app instances.
* :class:`InMemoryRateLimitStore` - process-local, for local dev and tests.

Both expose a single method::

    check_and_consume(key, limit, window_seconds) -> RateLimitResult
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

__all__ = [
    "RateLimitResult",
    "RateLimitStore",
    "InMemoryRateLimitStore",
    "RedisRateLimitStore",
    "RateLimitStoreError",
    "build_store",
]


class RateLimitStoreError(RuntimeError):
    """Raised when the backing store cannot answer (infra failure)."""


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single check-and-consume call."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_at: int

    def as_headers(self) -> Dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, self.retry_after))
        return headers


def _validate(limit: int, window_seconds: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be a positive integer")


class RateLimitStore:
    """Interface implemented by every rate limit store."""

    name = "base"

    def check_and_consume(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def reset(self, key: Optional[str] = None) -> None:  # pragma: no cover - optional
        raise NotImplementedError


class InMemoryRateLimitStore(RateLimitStore):
    """Thread-safe in-process sliding window.

    ``clock`` is a callable returning the current time in seconds; tests inject
    a controllable clock so they never need to sleep.
    """

    name = "memory"

    def __init__(self, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock: Callable[[], float] = clock or time.time
        self._hits: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check_and_consume(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        _validate(limit, window_seconds)
        now = float(self._clock())
        cutoff = now - float(window_seconds)

        with self._lock:
            timestamps = self._hits.get(key, [])
            # Drop everything at or before the cutoff (entries exactly one
            # window old have expired), matching ZREMRANGEBYSCORE 0 cutoff.
            start = bisect_right(timestamps, cutoff)
            if start:
                timestamps = timestamps[start:]

            allowed = len(timestamps) < limit
            if allowed:
                timestamps.append(now)

            if timestamps:
                self._hits[key] = timestamps
                oldest = timestamps[0]
            else:
                self._hits.pop(key, None)
                oldest = now

            count = len(timestamps)

        reset_ts = oldest + float(window_seconds)
        return _build_result(now, reset_ts, count, limit, allowed)

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# KEYS[1] = rate limit key
# ARGV[1] = now (ms), ARGV[2] = window (ms), ARGV[3] = limit, ARGV[4] = member
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
local count = redis.call('ZCARD', key)
local allowed = 0
if count < limit then
  redis.call('ZADD', key, now_ms, member)
  count = count + 1
  allowed = 1
end
redis.call('PEXPIRE', key, window_ms)

local reset_ms = now_ms + window_ms
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if oldest[2] then
  reset_ms = tonumber(oldest[2]) + window_ms
end
return {allowed, count, reset_ms}
"""


class RedisRateLimitStore(RateLimitStore):
    """Redis-backed sliding window using one atomic Lua script per request."""

    name = "redis"

    def __init__(
        self,
        client,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._client = client
        self._clock: Callable[[], float] = clock or time.time
        self._script = None

    @classmethod
    def from_url(
        cls,
        url: str,
        timeout_seconds: float = 0.25,
        clock: Optional[Callable[[], float]] = None,
    ) -> "RedisRateLimitStore":
        try:
            import redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RateLimitStoreError(
                "REDIS_URL is configured but the 'redis' package is not installed"
            ) from exc

        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            retry_on_timeout=False,
            decode_responses=False,
        )
        return cls(client, clock=clock)

    def _get_script(self):
        if self._script is None:
            self._script = self._client.register_script(SLIDING_WINDOW_LUA)
        return self._script

    def check_and_consume(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        _validate(limit, window_seconds)
        now = float(self._clock())
        now_ms = int(now * 1000)
        window_ms = int(window_seconds) * 1000
        member = f"{now_ms}-{uuid.uuid4().hex}"

        try:
            script = self._get_script()
            raw = script(keys=[key], args=[now_ms, window_ms, limit, member])
        except RateLimitStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - any redis/infra failure
            raise RateLimitStoreError(f"redis rate limit check failed: {exc}") from exc

        try:
            allowed = bool(int(raw[0]))
            count = int(raw[1])
            reset_ms = float(raw[2])
        except (TypeError, ValueError, IndexError) as exc:
            raise RateLimitStoreError(
                f"unexpected redis script response: {raw!r}"
            ) from exc

        return _build_result(now, reset_ms / 1000.0, count, limit, allowed)

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            raise ValueError("RedisRateLimitStore.reset requires an explicit key")
        try:
            self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            raise RateLimitStoreError(str(exc)) from exc


def _build_result(
    now: float, reset_ts: float, count: int, limit: int, allowed: bool
) -> RateLimitResult:
    remaining = max(0, limit - count)
    retry_after = 0 if allowed else max(1, int(math.ceil(reset_ts - now)))
    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=remaining,
        retry_after=retry_after,
        reset_at=int(math.ceil(reset_ts)),
    )


def build_store(settings=None, clock: Optional[Callable[[], float]] = None) -> RateLimitStore:
    """Pick the store implementation for the current configuration.

    Redis when ``REDIS_URL`` is set, in-memory otherwise. If Redis cannot be
    constructed at all we fall back to the in-memory store so the app still
    boots (the limiter also fails open at request time).
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    if settings.redis_url:
        try:
            return RedisRateLimitStore.from_url(
                settings.redis_url,
                timeout_seconds=settings.redis_timeout_seconds,
                clock=clock,
            )
        except RateLimitStoreError:
            import logging

            logging.getLogger(__name__).warning(
                "rate_limit_store_init_failed backend=redis falling_back=memory",
                exc_info=True,
            )
    return InMemoryRateLimitStore(clock=clock)
