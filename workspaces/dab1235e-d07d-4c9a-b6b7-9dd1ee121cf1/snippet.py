"""DEPRECATED shim.

The original single-file snippet was restructured into the ``app/`` package.
This file only re-exports the ASGI application so any old command such as
``uvicorn snippet:app`` keeps working; it contains no logic and can be removed.

Use instead:
    uvicorn app.main:app --reload
    python run.py
"""

import warnings

from app.main import app  # noqa: F401  (re-exported for backwards compatibility)

warnings.warn(
    "snippet.py is deprecated; use 'app.main:app' (see README).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["app"]
