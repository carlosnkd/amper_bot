"""Application wiring: routes, auth, and the chat rate limiter."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.auth import authenticate
from app.config import Settings, get_settings
from app.errors import error_envelope
from app.http import Request, Response, Router, TestClient, json_response
from app.model_client import EchoModelClient, ModelClient
from app.ratelimit.limiter import ChatRateLimiter
from app.ratelimit.middleware import rate_limit_chat
from app.ratelimit.store import RateLimitStore

__all__ = ["App", "create_app"]

logger = logging.getLogger("app")


class App:
    """Holds the app dependencies and dispatches requests."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        model_client: Optional[ModelClient] = None,
        store: Optional[RateLimitStore] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_client = model_client or EchoModelClient()
        self.chat_limiter = ChatRateLimiter(
            store=store, settings=self.settings, clock=clock
        )
        self.router = Router()
        self._register_routes()

    # -- routes -----------------------------------------------------------
    def _register_routes(self) -> None:
        self.router.add("GET", "/healthz", self.healthz)
        self.router.add(
            "POST",
            "/chat",
            rate_limit_chat(lambda: self.chat_limiter, endpoint="/chat")(self.chat),
        )

    def handle(self, request: Request) -> Response:
        authenticate(request)
        return self.router.dispatch(request)

    def client(self) -> TestClient:
        return TestClient(self)

    # -- handlers ---------------------------------------------------------
    def healthz(self, request: Request) -> Response:
        return json_response({"status": "ok"})

    def chat(self, request: Request) -> Response:
        """POST /chat.

        Rate limited to RATE_LIMIT_CHAT_MAX_REQUESTS requests per
        RATE_LIMIT_CHAT_WINDOW_SECONDS (default 10 / 60s) per authenticated
        user, or per client IP for anonymous callers.

        Responses:
            200 - {"message": {...}}
            400 - invalid request body
            429 - {"error": {"code": "rate_limit_exceeded", "message": "..."}}
                  with Retry-After and X-RateLimit-* headers.
        """
        payload: Any = request.json() or {}
        if not isinstance(payload, dict):
            return json_response(
                error_envelope("invalid_request", "Request body must be a JSON object"),
                400,
            )

        messages = payload.get("messages")
        if messages is None and payload.get("message") is not None:
            messages = [{"role": "user", "content": payload["message"]}]
        if not isinstance(messages, list) or not messages:
            return json_response(
                error_envelope(
                    "invalid_request", "Field 'messages' must be a non-empty array"
                ),
                400,
            )

        reply = self.model_client.complete(messages)
        return json_response({"message": reply})


def create_app(
    settings: Optional[Settings] = None,
    model_client: Optional[ModelClient] = None,
    store: Optional[RateLimitStore] = None,
    clock: Optional[Callable[[], float]] = None,
) -> App:
    return App(settings=settings, model_client=model_client, store=store, clock=clock)
