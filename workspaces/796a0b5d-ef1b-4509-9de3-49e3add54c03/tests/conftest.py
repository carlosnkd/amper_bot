"""Shared test fixtures: controllable clock, in-memory store, app factory."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import metrics  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.model_client import ModelClient  # noqa: E402
from app.ratelimit.store import InMemoryRateLimitStore  # noqa: E402


class FakeClock:
    """Manually advanced clock so tests never sleep."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


class RecordingModelClient(ModelClient):
    """Model client that records every downstream invocation."""

    def __init__(self) -> None:
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return {"role": "assistant", "content": "pong"}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock) -> InMemoryRateLimitStore:
    return InMemoryRateLimitStore(clock=clock)


@pytest.fixture
def model_client() -> RecordingModelClient:
    return RecordingModelClient()


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def make_app(clock, store, model_client):
    def factory(**overrides):
        settings = Settings(
            rate_limit_enabled=overrides.pop("rate_limit_enabled", True),
            rate_limit_chat_max_requests=overrides.pop(
                "rate_limit_chat_max_requests", 10
            ),
            rate_limit_chat_window_seconds=overrides.pop(
                "rate_limit_chat_window_seconds", 60
            ),
            redis_url=overrides.pop("redis_url", None),
            trust_proxy_headers=overrides.pop("trust_proxy_headers", False),
            trusted_proxies=tuple(overrides.pop("trusted_proxies", ())),
        )
        assert not overrides, f"unknown overrides: {sorted(overrides)}"
        return create_app(
            settings=settings,
            model_client=model_client,
            store=store,
            clock=clock,
        )

    return factory


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.client()
