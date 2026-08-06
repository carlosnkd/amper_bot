"""API route handlers."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from app.api.schemas import ErrorResponse, HealthResponse, ItemResponse, RootResponse
from app.core.logging import get_logger
from app.repository import items as items_repo

logger = get_logger("app.api.routes")

router = APIRouter()


@router.get("/", response_model=RootResponse, tags=["root"])
def read_root() -> RootResponse:
    """Return the greeting payload (behaviour unchanged from the snippet)."""
    return RootResponse(message="Hello, World!")


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(request: Request) -> HealthResponse:
    """Liveness probe reporting the running application version."""
    return HealthResponse(status="ok", version=request.app.version)


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
    tags=["items"],
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
def read_item(
    item_id: int = Path(..., description="Numeric identifier of the item"),
    q: Optional[str] = Query(
        default=None, max_length=50, description="Optional query string"
    ),
) -> ItemResponse:
    """Return the item identifier plus the optional query string.

    Raises a 404 when the identifier is unknown to the repository.
    """
    item = items_repo.get_item(item_id)
    if item is None:
        logger.info("Item %s not found", item_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    return ItemResponse(item_id=item_id, q=q)
