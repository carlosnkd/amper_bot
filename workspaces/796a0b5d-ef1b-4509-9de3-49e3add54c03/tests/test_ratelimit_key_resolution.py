"""Unit tests for limit key resolution."""

from __future__ import annotations

from app.config import Settings
from app.http import Request
from app.ratelimit.middleware import client_ip, resolve_limit_key


def make_request(headers=None, remote_addr="192.0.2.10", auth=None) -> Request:
    return Request(
        method="POST",
        path="/chat",
        headers=headers or {},
        remote_addr=remote_addr,
        auth=auth,
    )


def test_authenticated_requests_keyed_by_user():
    request = make_request(auth={"user_id": "u-123"})
    assert resolve_limit_key(request, Settings()) == ("chat:user:u-123", "user", "u-123")


def test_anonymous_requests_keyed_by_peer_address():
    request = make_request()
    assert resolve_limit_key(request, Settings()) == (
        "chat:ip:192.0.2.10",
        "ip",
        "192.0.2.10",
    )


def test_forwarded_for_ignored_when_not_trusted():
    request = make_request(headers={"X-Forwarded-For": "203.0.113.1"})
    assert client_ip(request, Settings(trust_proxy_headers=False)) == "192.0.2.10"


def test_first_non_proxy_forwarded_entry_used_when_trusted():
    settings = Settings(trust_proxy_headers=True, trusted_proxies=("10.0.0.1",))
    request = make_request(
        headers={"X-Forwarded-For": "10.0.0.1, 203.0.113.4, 10.0.0.1"},
        remote_addr="10.0.0.1",
    )
    assert client_ip(request, settings) == "203.0.113.4"


def test_falls_back_to_peer_when_forwarded_header_absent():
    settings = Settings(trust_proxy_headers=True)
    assert client_ip(make_request(), settings) == "192.0.2.10"


def test_unknown_when_no_peer_address():
    settings = Settings()
    request = make_request(remote_addr=None)
    assert client_ip(request, settings) == "unknown"
