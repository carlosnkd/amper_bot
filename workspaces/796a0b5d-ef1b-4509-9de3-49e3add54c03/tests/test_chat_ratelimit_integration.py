"""Integration tests for the rate limit on POST /chat."""

from __future__ import annotations

import logging

from app import metrics

BODY = {"messages": [{"role": "user", "content": "hi"}]}
ALICE = {"Authorization": "Bearer user:alice"}
BOB = {"Authorization": "Bearer user:bob"}


def post(client, headers=None, remote_addr="198.51.100.7"):
    return client.post(
        "/chat", json_body=BODY, headers=headers or {}, remote_addr=remote_addr
    )


def test_first_ten_requests_succeed_with_headers(client, clock):
    for i in range(10):
        response = post(client, ALICE)
        assert response.status == 200
        assert response.body["message"]["content"] == "pong"
        assert response.headers["X-RateLimit-Limit"] == "10"
        assert response.headers["X-RateLimit-Remaining"] == str(9 - i)
        assert response.headers["X-RateLimit-Reset"] == str(int(clock.now) + 60)
        assert "Retry-After" not in response.headers


def test_eleventh_request_returns_429_envelope_and_headers(client, clock):
    for _ in range(10):
        post(client, ALICE)

    response = post(client, ALICE)
    assert response.status == 429
    assert response.body == {
        "error": {
            "code": "rate_limit_exceeded",
            "message": "Too many messages. Try again in 60 seconds.",
        }
    }
    assert response.headers["Retry-After"] == "60"
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Reset"] == str(int(clock.now) + 60)


def test_retry_after_counts_down_within_the_window(client, clock):
    for _ in range(10):
        post(client, ALICE)
    clock.advance(45)
    response = post(client, ALICE)
    assert response.status == 429
    assert response.headers["Retry-After"] == "15"
    assert "Try again in 15 seconds" in response.body["error"]["message"]


def test_model_is_not_called_when_rejected(client, model_client):
    for _ in range(10):
        post(client, ALICE)
    assert len(model_client.calls) == 10

    assert post(client, ALICE).status == 429
    assert len(model_client.calls) == 10, "downstream model must not be invoked"


def test_window_expiry_allows_traffic_again(client, clock):
    for _ in range(10):
        post(client, ALICE)
    assert post(client, ALICE).status == 429

    clock.advance(60)
    response = post(client, ALICE)
    assert response.status == 200
    assert response.headers["X-RateLimit-Remaining"] == "9"


def test_users_do_not_share_a_budget(client):
    for _ in range(10):
        assert post(client, ALICE).status == 200
    assert post(client, ALICE).status == 429
    assert post(client, BOB).status == 200


def test_unauthenticated_callers_are_keyed_by_ip(client):
    for _ in range(10):
        assert post(client, remote_addr="203.0.113.5").status == 200
    assert post(client, remote_addr="203.0.113.5").status == 429
    # different IP has its own budget
    assert post(client, remote_addr="203.0.113.6").status == 200
    # an authenticated user from the exhausted IP is keyed by user id
    assert post(client, ALICE, remote_addr="203.0.113.5").status == 200


def test_x_forwarded_for_used_when_proxy_headers_trusted(make_app):
    app = make_app(trust_proxy_headers=True, trusted_proxies=("10.0.0.1",))
    client = app.client()
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
    for _ in range(10):
        assert client.post(
            "/chat", json_body=BODY, headers=headers, remote_addr="10.0.0.1"
        ).status == 200
    assert client.post(
        "/chat", json_body=BODY, headers=headers, remote_addr="10.0.0.1"
    ).status == 429
    # a different real client behind the same proxy is unaffected
    assert client.post(
        "/chat",
        json_body=BODY,
        headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.1"},
        remote_addr="10.0.0.1",
    ).status == 200


def test_x_forwarded_for_ignored_when_proxy_headers_not_trusted(client):
    headers = {"X-Forwarded-For": "203.0.113.9"}
    for i in range(10):
        assert client.post(
            "/chat", json_body=BODY, headers=headers, remote_addr="10.0.0.1"
        ).status == 200
    # spoofing a new XFF does not reset the budget: peer address is the key
    assert client.post(
        "/chat",
        json_body=BODY,
        headers={"X-Forwarded-For": "203.0.113.99"},
        remote_addr="10.0.0.1",
    ).status == 429


def test_disabled_flag_turns_enforcement_off(make_app, model_client):
    app = make_app(rate_limit_enabled=False)
    client = app.client()
    for _ in range(25):
        assert client.post("/chat", json_body=BODY, headers=ALICE).status == 200
    assert len(model_client.calls) == 25


def test_configurable_limit_and_window(make_app):
    app = make_app(rate_limit_chat_max_requests=2, rate_limit_chat_window_seconds=5)
    client = app.client()
    assert client.post("/chat", json_body=BODY, headers=ALICE).status == 200
    second = client.post("/chat", json_body=BODY, headers=ALICE)
    assert second.status == 200
    assert second.headers["X-RateLimit-Limit"] == "2"
    third = client.post("/chat", json_body=BODY, headers=ALICE)
    assert third.status == 429
    assert third.headers["Retry-After"] == "5"


def test_limiter_is_not_applied_globally(client):
    for _ in range(50):
        assert client.get("/healthz").status == 200
    response = client.get("/healthz")
    assert "X-RateLimit-Limit" not in response.headers


def test_rejection_emits_log_and_metric(client, caplog):
    for _ in range(10):
        post(client, ALICE)

    with caplog.at_level(logging.WARNING, logger="app.ratelimit"):
        assert post(client, ALICE).status == 429

    records = [r for r in caplog.records if getattr(r, "event", "") == "rate_limit_rejected"]
    assert records, "expected a structured rejection log line"
    record = records[0]
    assert record.endpoint == "/chat"
    assert record.key_type == "user"
    assert record.identifier == "alice"

    assert (
        metrics.get(
            metrics.RATE_LIMIT_REJECTIONS_TOTAL,
            labels={"endpoint": "/chat", "key_type": "user"},
        )
        == 1
    )


def test_ip_rejection_metric_labelled_ip(client):
    for _ in range(11):
        post(client, remote_addr="203.0.113.77")
    assert (
        metrics.get(
            metrics.RATE_LIMIT_REJECTIONS_TOTAL,
            labels={"endpoint": "/chat", "key_type": "ip"},
        )
        == 1
    )


def test_invalid_body_still_counted_but_returns_400(client):
    response = client.post("/chat", json_body={"messages": []}, headers=ALICE)
    assert response.status == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert response.headers["X-RateLimit-Remaining"] == "9"
