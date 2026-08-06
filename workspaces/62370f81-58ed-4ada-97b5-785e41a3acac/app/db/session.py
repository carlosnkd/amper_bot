"""Database session dependency.

``get_db`` is intentionally *not* used by the health router: the liveness
probe must succeed even when the database is unreachable.
"""

from __future__ import annotations

from typing import Any, Iterator


class Database:
    """Minimal stand-in session object for the example service."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def ping(self) -> bool:
        if self.closed:
            raise RuntimeError("Session already closed.")
        return True

    def close(self) -> None:
        self.closed = True


def get_db() -> Iterator[Any]:
    """Yield a database session, closing it afterwards."""
    from app.core.config import get_settings

    db = Database(get_settings().database_url)
    try:
        yield db
    finally:
        db.close()
