"""Fail-open behaviour and log rate limiting when the store is unhealthy."""

from __future__ import annotations

import logging

import pytest

from app.config import Settings
from app.main import create_app
from app.ratelimit.limiter import ChatRateLimiter
from app.ratelimit.store import RateLimitStore, RateLimitStoreError
from tests.conftest import FakeClock, RecordingModelClient

BODY = {"messages": [{"role": "user", "content": "hi"}]}
ALICE = {"Authorization": "Bearer user:alice"}


class BrokenStore(RateLimitStore):
    name = "broken"

    def __init__(self, exc=None) -> None:
        self.calls = 0
        self.exc = exc or RateLimitStoreError("redis unreachable")

    def check_and_consume(self, key, limit, window_seconds):
        self.calls += 1
        raise self.exc


def test_chat_still_serves_traffic_when_store_is_down():
    clock = FakeClock()
    model = RecordingModelClient()
    app = create_app(
        settings=Settings(),
        model_client=model,
        store=BrokenStore(),
        clock=clock,
    )
    client = app.client()

    for _ in range(30):
        response = client.post("/chat", json_body=BODY, headers=ALICE)
        assert response.status == 200
        assert response.headers["X-RateLimit-Limit"] == "10"
    assert len(model.calls) == 30


@pytest.mark.parametrize(
    "exc", [RateLimitStoreError("boom"), ConnectionError("refused"), TimeoutError()]
)
def test_any_infra_exception_fails_open(exc):
    clock = FakeClock()
    limiter = ChatRateLimiter(store=BrokenStore(exc), settings=Settings(), clock=clock)
    decision = limiter.check("chat:user:alice", "user", "alice")
    assert decision.allowed is True
    assert decision.failed_open is True


def test_infra_warning_is_rate_limited(caplog):
    clock = FakeClock()
    limiter = ChatRateLimiter(store=BrokenStore(), settings=Settings(), clock=clock)

    with caplog.at_level(logging.WARNING, logger="app.ratelimit"):
        for _ in range(100):
            limiter.check("chat:user:alice", "user", "alice")

        records = [
            r
            for r in caplog.records
            if getattr(r, "event", "") == "rate_limit_store_unavailable"
        ]
        assert len(records) == 1, "warning must not be emitted per request"
        assert records[0].failing_open is True

        # after the suppression interval a new warning is emitted, carrying
        # the number of suppressed occurrences
        clock.advance(31)
        limiter.check("chat:user:alice", "user", "alice")
        records = [
            r
            for r in caplog.records
            if getattr(r, "event", "") == "rate_limit_store_unavailable"
        ]
        assert len(records) == 2
        assert records[1].suppressed_since_last_log == 99


def test_disabled_limiter_never_touches_the_store():
    store = BrokenStore()
    limiter = ChatRateLimiter(
        store=store, settings=Settings(rate_limit_enabled=False), clock=FakeClock()
    )
    decision = limiter.check("chat:user:alice", "user", "alice")
    assert decision.allowed is True
    assert decision.enforced is False
    assert store.calls == 0
