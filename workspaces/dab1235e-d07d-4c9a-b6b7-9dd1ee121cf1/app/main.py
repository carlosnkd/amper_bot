"""ASGI entrypoint: builds and configures the FastAPI application."""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


def error_payload(detail: Any, status_code: int) -> Dict[str, Any]:
    """Build the consistent error envelope used by every handler."""
    return {"detail": detail, "status_code": status_code}


def serialisable_errors(exc: RequestValidationError) -> List[Dict[str, Any]]:
    """Convert validation errors into a JSON-serialisable list."""
    return [
        {
            "loc": [str(part) for part in error.get("loc", [])],
            "msg": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or get_settings()
    logger = configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "%s v%s starting (debug=%s)",
            settings.app_name,
            settings.app_version,
            settings.debug,
        )
        yield
        logger.info("%s shutting down", settings.app_name)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.include_router(router)

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Return HTTP errors (including 404s) in the shared envelope."""
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.detail, exc.status_code),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return 422 validation problems in the shared envelope."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload(
                serialisable_errors(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Log unexpected errors and return a generic 500 without a traceback."""
        logger.exception(
            "Unhandled error while processing %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(
                "Internal Server Error", status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
        )

    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover - dev convenience only
    import uvicorn

    _settings = get_settings()
    uvicorn.run(app, host=_settings.host, port=_settings.port)
