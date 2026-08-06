"""Unit tests for the sliding-window stores."""

from __future__ import annotations

import pytest

from app.ratelimit.store import (
    InMemoryRateLimitStore,
    RateLimitStoreError,
    RedisRateLimitStore,
    build_store,
)
from app.config import Settings
from tests.conftest import FakeClock

LIMIT = 10
WINDOW = 60


def consume(store, key="chat:user:u1", limit=LIMIT, window=WINDOW):
    return store.check_and_consume(key, limit, window)


def test_tenth_request_allowed_eleventh_rejected(store, clock):
    results = [consume(store) for _ in range(LIMIT)]
    assert all(r.allowed for r in results)
    assert [r.remaining for r in results] == list(range(LIMIT - 1, -1, -1))

    rejected = consume(store)
    assert rejected.allowed is False
    assert rejected.remaining == 0
    assert rejected.limit == LIMIT
    assert rejected.retry_after == WINDOW
    assert rejected.reset_at == int(clock.now) + WINDOW


def test_rejected_requests_do_not_extend_the_window(store, clock):
    for _ in range(LIMIT):
        consume(store)
    clock.advance(30)
    first_reject = consume(store)
    assert first_reject.allowed is False
    assert first_reject.retry_after == 30  # window still ends at t0 + 60

    clock.advance(20)
    second_reject = consume(store)
    assert second_reject.allowed is False
    assert second_reject.retry_after == 10


def test_window_expiry_allows_requests_again(store, clock):
    for _ in range(LIMIT):
        consume(store)
    assert consume(store).allowed is False

    clock.advance(WINDOW)  # entire window has rolled off
    allowed = consume(store)
    assert allowed.allowed is True
    assert allowed.remaining == LIMIT - 1


def test_sliding_window_across_a_bucket_boundary(store, clock):
    """A user cannot burst 2x the limit across a calendar-minute boundary."""
    for _ in range(LIMIT):
        consume(store)  # t = 0, budget exhausted

    clock.advance(59)  # still inside the window
    assert consume(store).allowed is False

    clock.advance(1)  # t = 60, the original 10 have expired
    burst = [consume(store) for _ in range(LIMIT)]
    assert all(r.allowed for r in burst)
    assert consume(store).allowed is False  # 11th in the new window rejected


def test_partial_window_rolloff(store, clock):
    for _ in range(5):
        consume(store)
    clock.advance(30)
    for _ in range(5):
        consume(store)  # limit reached at t = 30
    assert consume(store).allowed is False

    clock.advance(31)  # t = 61: the first five have expired, the later five have not
    allowed = [consume(store) for _ in range(5)]
    assert all(r.allowed for r in allowed)
    assert consume(store).allowed is False


def test_per_key_isolation(store):
    for _ in range(LIMIT):
        assert consume(store, key="chat:user:alice").allowed is True
    assert consume(store, key="chat:user:alice").allowed is False

    bob = consume(store, key="chat:user:bob")
    assert bob.allowed is True
    assert bob.remaining == LIMIT - 1

    ip_key = consume(store, key="chat:ip:203.0.113.9")
    assert ip_key.allowed is True


def test_headers_helper(store):
    allowed = consume(store)
    headers = allowed.as_headers()
    assert headers["X-RateLimit-Limit"] == str(LIMIT)
    assert headers["X-RateLimit-Remaining"] == str(LIMIT - 1)
    assert "Retry-After" not in headers

    for _ in range(LIMIT):
        consume(store)
    rejected = consume(store)
    assert rejected.as_headers()["Retry-After"] == str(rejected.retry_after)


@pytest.mark.parametrize("limit,window", [(0, 60), (-1, 60), (10, 0), (10, -5)])
def test_invalid_policy_rejected(store, limit, window):
    with pytest.raises(ValueError):
        store.check_and_consume("k", limit, window)


def test_reset_clears_state(store):
    for _ in range(LIMIT):
        consume(store)
    assert consume(store).allowed is False
    store.reset("chat:user:u1")
    assert consume(store).allowed is True


def test_build_store_defaults_to_memory():
    built = build_store(Settings(redis_url=None))
    assert isinstance(built, InMemoryRateLimitStore)


def test_build_store_falls_back_to_memory_when_redis_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise RateLimitStoreError("no redis package")

    monkeypatch.setattr(RedisRateLimitStore, "from_url", staticmethod(boom))
    built = build_store(Settings(redis_url="redis://localhost:6379/0"))
    assert isinstance(built, InMemoryRateLimitStore)


# --- Redis-backed store (with a stubbed script runner) --------------------


class _FakeScript:
    """Python re-implementation of the Lua script, for wiring-level tests."""

    def __init__(self) -> None:
        self.zsets = {}

    def __call__(self, keys, args):
        key = keys[0]
        now_ms, window_ms, limit, member = (
            int(args[0]),
            int(args[1]),
            int(args[2]),
            args[3],
        )
        entries = [e for e in self.zsets.get(key, []) if e[0] > now_ms - window_ms]
        allowed = 0
        if len(entries) < limit:
            entries.append((now_ms, member))
            allowed = 1
        entries.sort()
        self.zsets[key] = entries
        reset_ms = (entries[0][0] + window_ms) if entries else now_ms + window_ms
        return [allowed, len(entries), reset_ms]


class _FakeRedis:
    def __init__(self, script=None, fail=False) -> None:
        self._script = script or _FakeScript()
        self.fail = fail
        self.registered = []
        self.deleted = []

    def register_script(self, source):
        self.registered.append(source)
        if self.fail:
            raise ConnectionError("redis is down")
        return self._script

    def delete(self, key):
        self.deleted.append(key)


def test_redis_store_matches_memory_semantics():
    clock = FakeClock()
    redis_store = RedisRateLimitStore(_FakeRedis(), clock=clock)
    memory_store = InMemoryRateLimitStore(clock=clock)

    for _ in range(LIMIT + 2):
        r = redis_store.check_and_consume("k", LIMIT, WINDOW)
        m = memory_store.check_and_consume("k", LIMIT, WINDOW)
        assert (r.allowed, r.remaining, r.retry_after) == (
            m.allowed,
            m.remaining,
            m.retry_after,
        )

    clock.advance(WINDOW)
    assert redis_store.check_and_consume("k", LIMIT, WINDOW).allowed is True


def test_redis_store_raises_store_error_on_connection_failure():
    store = RedisRateLimitStore(_FakeRedis(fail=True))
    with pytest.raises(RateLimitStoreError):
        store.check_and_consume("k", LIMIT, WINDOW)


def test_redis_store_raises_on_unexpected_reply():
    class Weird:
        def register_script(self, source):
            return lambda keys, args: "nonsense"

    store = RedisRateLimitStore(Weird())
    with pytest.raises(RateLimitStoreError):
        store.check_and_consume("k", LIMIT, WINDOW)


def test_redis_from_url_sets_short_timeouts(monkeypatch):
    captured = {}

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(url, **kwargs):
                captured["url"] = url
                captured.update(kwargs)
                return _FakeRedis()

    monkeypatch.setitem(__import__("sys").modules, "redis", FakeRedisModule)
    RedisRateLimitStore.from_url("redis://localhost:6379/0", timeout_seconds=0.25)
    assert captured["socket_connect_timeout"] == 0.25
    assert captured["socket_timeout"] == 0.25
