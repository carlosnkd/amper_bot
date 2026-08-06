"""Example business router: authenticated and DB-backed.

Included under the ``/api/v1`` prefix with the global API-key dependency,
which is exactly the group ``/health`` is kept out of.
"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.session import get_db

router = APIRouter(prefix="/items", tags=["items"])


class Item(BaseModel):
    id: int
    name: str


_FAKE_ITEMS: List[Item] = [Item(id=1, name="widget"), Item(id=2, name="gadget")]


@router.get("", response_model=List[Item], summary="List items")
async def list_items(db: Any = Depends(get_db)) -> List[Item]:
    db.ping()
    return _FAKE_ITEMS
