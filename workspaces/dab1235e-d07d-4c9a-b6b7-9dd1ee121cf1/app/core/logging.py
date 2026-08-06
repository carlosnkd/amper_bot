"""Logging configuration, applied exactly once at application startup."""

import logging

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure stdlib logging once and return the application logger."""
    global _CONFIGURED

    if not _CONFIGURED:
        logging.basicConfig(
            level=getattr(logging, str(level).upper(), logging.INFO),
            format=LOG_FORMAT,
        )
        _CONFIGURED = True

    return logging.getLogger("app")


def get_logger(name: str = "app") -> logging.Logger:
    """Return a named child logger of the application logger."""
    return logging.getLogger(name)
