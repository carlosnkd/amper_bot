"""In-memory item store.

Kept deliberately dumb so it can be swapped for a real database later without
touching the route handlers.
"""

from typing import Any, Dict, Optional

# item_id -> item payload
_ITEMS: Dict[int, Dict[str, Any]] = {
    1: {"item_id": 1, "name": "Hammer"},
    2: {"item_id": 2, "name": "Nail"},
    3: {"item_id": 3, "name": "Screwdriver"},
}


def get_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Return the item with ``item_id`` or ``None`` when it does not exist."""
    return _ITEMS.get(item_id)


def list_items() -> Dict[int, Dict[str, Any]]:
    """Return a shallow copy of the whole store."""
    return dict(_ITEMS)


def add_item(item_id: int, **fields: Any) -> Dict[str, Any]:
    """Insert or replace an item and return it."""
    item = {"item_id": item_id, **fields}
    _ITEMS[item_id] = item
    return item


def clear() -> None:
    """Remove every item. Primarily used by tests."""
    _ITEMS.clear()


def reset(items: Optional[Dict[int, Dict[str, Any]]] = None) -> None:
    """Replace the store contents with ``items`` (defaults to empty)."""
    _ITEMS.clear()
    if items:
        _ITEMS.update(items)
