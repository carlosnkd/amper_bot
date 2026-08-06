"""Downstream model client (stand-in for the real provider SDK)."""

from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["ModelClient", "EchoModelClient"]


class ModelClient:
    """Interface for the downstream model call."""

    def complete(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


class EchoModelClient(ModelClient):
    """Default implementation used in dev/tests; counts its invocations."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls += 1
        last = messages[-1] if messages else {"content": ""}
        return {
            "role": "assistant",
            "content": f"echo: {last.get('content', '')}",
        }
