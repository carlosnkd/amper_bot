"""Shared pytest fixtures."""

import os
import sys
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Make the project root importable when pytest is invoked from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repository import items as items_repo  # noqa: E402

SEED_ITEMS = {
    1: {"item_id": 1, "name": "Hammer"},
    2: {"item_id": 2, "name": "Nail"},
}

TEST_VERSION = "1.0.0"


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests."""
    return Settings(
        app_name="Snippet API (test)",
        app_version=TEST_VERSION,
        host="127.0.0.1",
        port=8000,
        debug=False,
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def seeded_store() -> Iterator[dict]:
    """Seed the in-memory store before each test and restore it afterwards."""
    original = items_repo.list_items()
    items_repo.reset({key: dict(value) for key, value in SEED_ITEMS.items()})
    yield items_repo.list_items()
    items_repo.reset(original)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """TestClient bound to a freshly built app instance."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
