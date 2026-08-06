"""Tests for the global error handlers."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert "detail" in body


def test_unexpected_error_returns_generic_500():
    app = create_app(Settings(log_level="CRITICAL"))

    @app.get("/boom")
    def boom():  # pragma: no cover - executed through the test client
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal Server Error",
        "status_code": 500,
    }
    assert "kaboom" not in response.text
