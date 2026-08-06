"""Example protected router.

Exists so the global auth/rate-limit middleware has something to guard; it is
mounted under the ``/api/v1`` prefix, unlike the public system routes.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["items"])


@router.get("/items", summary="List items")
async def list_items() -> List[Dict[str, str]]:
    """Return a static list of items (requires a valid API key)."""
    return [{"id": "1", "name": "widget"}]
