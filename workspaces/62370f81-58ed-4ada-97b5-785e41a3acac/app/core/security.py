"""API-key authentication used as a global dependency on the versioned API.

The health router is included *outside* the group that carries this
dependency, so liveness probes never need credentials.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


async def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject the request unless a valid API key header is present.

    Public paths (see ``Settings.public_paths``) are always allowed; this is a
    belt-and-braces exemption in case the dependency is ever attached higher up
    in the app than intended.
    """
    if settings.is_public_path(request.url.path):
        return

    provided = request.headers.get(settings.api_key_header)
    if not provided or provided != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": settings.api_key_header},
        )
