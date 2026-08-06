"""Chat service application package."""

__all__ = ["create_app"]


def create_app(*args, **kwargs):  # pragma: no cover - thin re-export
    from app.main import create_app as _create_app

    return _create_app(*args, **kwargs)
