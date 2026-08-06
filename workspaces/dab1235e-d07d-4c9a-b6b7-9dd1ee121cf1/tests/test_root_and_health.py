"""Tests for the root and health endpoints."""

from tests.conftest import TEST_VERSION


def test_read_root_returns_greeting(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello, World!"}


def test_health_returns_ok_and_version(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": TEST_VERSION}
