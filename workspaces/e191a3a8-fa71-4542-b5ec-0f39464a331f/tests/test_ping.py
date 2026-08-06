"""Tests for the public liveness probe GET /ping."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.security import API_KEY_HEADER


def test_ping_returns_200_and_pong_true(client: TestClient) -> None:
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"pong": True}


def test_ping_requires_no_auth_headers(client: TestClient) -> None:
    # Explicitly no credentials supplied.
    response = client.get("/ping", headers={})

    assert response.status_code == 200
    assert API_KEY_HEADER not in response.request.headers
    assert response.json() == {"pong": True}


def test_ping_is_not_rate_limited(settings, client: TestClient) -> None:
    for _ in range(settings.rate_limit_requests + 5):
        response = client.get("/ping")
        assert response.status_code == 200


def test_protected_route_still_requires_api_key(client: TestClient) -> None:
    assert client.get("/api/v1/items").status_code == 401
    ok = client.get("/api/v1/items", headers={API_KEY_HEADER: "test-key"})
    assert ok.status_code == 200


def test_ping_documented_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/ping"]["get"]

    assert operation["summary"] == "Liveness probe"
    assert operation["tags"] == ["system"]
    assert "PingResponse" in str(operation["responses"]["200"])
