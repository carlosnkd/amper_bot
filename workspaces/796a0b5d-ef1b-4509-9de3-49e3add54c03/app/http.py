"""A tiny, dependency-free HTTP layer (request/response/router + test client).

The real service is expected to run behind a WSGI server; this module keeps the
surface small enough that the rate-limit code and its tests do not depend on a
particular web framework. Handlers have the signature ``handler(request) ->
Response | dict | (body, status) | (body, status, headers)``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.errors import ApiError

__all__ = ["Request", "Response", "Router", "TestClient", "json_response"]


class _Headers(dict):
    """Case-insensitive header mapping."""

    def __init__(self, initial: Optional[Dict[str, str]] = None) -> None:
        super().__init__()
        for key, value in (initial or {}).items():
            self[key] = value

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key.lower(), str(value))

    def __getitem__(self, key: str) -> str:
        return super().__getitem__(key.lower())

    def __contains__(self, key: object) -> bool:  # type: ignore[override]
        return super().__contains__(str(key).lower())

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(key.lower(), default)

    def update(self, other: Dict[str, Any]) -> None:  # type: ignore[override]
        for key, value in other.items():
            self[key] = value


@dataclass
class Request:
    """Incoming request, including the authenticated context (if any)."""

    method: str = "GET"
    path: str = "/"
    headers: _Headers = field(default_factory=_Headers)
    body: Any = None
    remote_addr: Optional[str] = None
    #: populated by the auth layer, e.g. {"user_id": "u-123"}
    auth: Optional[Dict[str, Any]] = None
    state: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.headers, _Headers):
            self.headers = _Headers(dict(self.headers or {}))
        self.method = self.method.upper()

    @property
    def user_id(self) -> Optional[str]:
        if not self.auth:
            return None
        user_id = self.auth.get("user_id") or self.auth.get("id")
        return str(user_id) if user_id else None

    def json(self) -> Any:
        if isinstance(self.body, (dict, list)) or self.body is None:
            return self.body
        return json.loads(self.body)


@dataclass
class Response:
    body: Any = None
    status: int = 200
    headers: _Headers = field(default_factory=_Headers)

    def __post_init__(self) -> None:
        if not isinstance(self.headers, _Headers):
            self.headers = _Headers(dict(self.headers or {}))
        self.headers.setdefault("content-type", "application/json")

    def json(self) -> Any:
        return self.body


def json_response(
    body: Any, status: int = 200, headers: Optional[Dict[str, str]] = None
) -> Response:
    return Response(body=body, status=status, headers=_Headers(headers or {}))


def _coerce(result: Any) -> Response:
    if isinstance(result, Response):
        return result
    if isinstance(result, tuple):
        if len(result) == 2:
            return json_response(result[0], result[1])
        if len(result) == 3:
            return json_response(result[0], result[1], result[2])
        raise TypeError("handler tuple must be (body, status[, headers])")
    return json_response(result)


class Router:
    """Maps ``(method, path)`` to a handler."""

    def __init__(self) -> None:
        self._routes: Dict[Tuple[str, str], Callable[[Request], Any]] = {}

    def add(self, method: str, path: str, handler: Callable[[Request], Any]) -> None:
        self._routes[(method.upper(), path)] = handler

    def route(self, method: str, path: str) -> Callable:
        def decorator(handler: Callable[[Request], Any]) -> Callable:
            self.add(method, path, handler)
            return handler

        return decorator

    def routes(self) -> List[Tuple[str, str]]:
        return sorted(self._routes.keys())

    def dispatch(self, request: Request) -> Response:
        handler = self._routes.get((request.method, request.path))
        if handler is None:
            allowed = {m for (m, p) in self._routes if p == request.path}
            if allowed:
                return json_response(
                    {
                        "error": {
                            "code": "method_not_allowed",
                            "message": f"{request.method} not allowed on {request.path}",
                        }
                    },
                    405,
                    {"Allow": ", ".join(sorted(allowed))},
                )
            return json_response(
                {
                    "error": {
                        "code": "not_found",
                        "message": f"No route for {request.path}",
                    }
                },
                404,
            )
        try:
            return _coerce(handler(request))
        except ApiError as exc:
            response = json_response(exc.to_body(), exc.status)
            response.headers.update(exc.headers)
            return response


class TestClient:
    """Minimal client used by the integration tests."""

    def __init__(self, app) -> None:
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        remote_addr: str = "127.0.0.1",
        auth: Optional[Dict[str, Any]] = None,
    ) -> Response:
        request = Request(
            method=method,
            path=path,
            headers=_Headers(headers or {}),
            body=json_body,
            remote_addr=remote_addr,
            auth=auth,
        )
        return self.app.handle(request)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)
