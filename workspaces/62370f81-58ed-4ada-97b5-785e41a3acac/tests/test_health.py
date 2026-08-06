"""Tests for the GET /health liveness probe."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import require_api_key
from app.db.session import get_db
from app.main import create_app


def test_health_returns_200_and_exact_body(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_requires_no_auth_header(client: TestClient) -> None:
    """No API key, no Authorization header -> still 200."""
    response = client.get("/health", headers={})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # Sanity check: the versioned API *does* reject unauthenticated calls,
    # proving /health is genuinely exempt rather than auth being disabled.
    protected = client.get("/api/v1/items")
    assert protected.status_code == 401


def test_health_with_bogus_api_key_still_ok(client: TestClient) -> None:
    response = client.get("/health", headers={"X-API-Key": "definitely-wrong"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_health_rejects_non_get_methods(client: TestClient, method: str) -> None:
    response = getattr(client, method)("/health")

    assert response.status_code == 405


def test_health_ok_when_database_dependency_fails(app, client: TestClient) -> None:
    """The probe must stay green while downstream dependencies are down."""

    def broken_db():
        raise RuntimeError("database is down")

    app.dependency_overrides[get_db] = broken_db
    try:
        # The DB-backed route blows up...
        with pytest.raises(RuntimeError):
            client.get("/api/v1/items", headers={"X-API-Key": "local-dev-key"})

        # ...but the liveness probe does not depend on it.
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_health_not_mounted_under_version_prefix(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 404


def test_health_route_has_no_dependencies(app) -> None:
    route = next(r for r in app.routes if getattr(r, "path", None) == "/health")

    assert route.methods == {"GET"}
    assert route.dependencies == []
    assert require_api_key not in [
        dep.call for dep in route.dependant.dependencies
    ]


def test_health_in_openapi_schema_under_health_tag(app) -> None:
    schema = app.openapi()
    operation = schema["paths"]["/health"]["get"]

    assert operation["tags"] == ["health"]
    assert operation["summary"] == "Liveness probe"

    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    model_name = body["$ref"].rsplit("/", 1)[-1]
    model = schema["components"]["schemas"][model_name]
    assert "status" in model["properties"]


def test_health_is_not_rate_limited() -> None:
    """Hammering /health past the limit must never yield 429."""
    tight = Settings(rate_limit_enabled=True, rate_limit_requests=2)

    with TestClient(create_app(tight)) as client:
        statuses = {client.get("/health").status_code for _ in range(10)}

    assert statuses == {200}


def test_versioned_api_is_still_rate_limited() -> None:
    """Regression guard: the exemption applies to /health only."""
    tight = Settings(rate_limit_enabled=True, rate_limit_requests=2)

    with TestClient(create_app(tight)) as client:
        headers = {"X-API-Key": tight.api_key}
        statuses = [
            client.get("/api/v1/items", headers=headers).status_code
            for _ in range(5)
        ]

    assert 429 in statuses
