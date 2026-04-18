"""Shared logging configuration for Inky Image Display services."""

import logging
import os

from rich.logging import RichHandler


def setup_logging(level: int | None = None) -> None:
    """Configure root logger with Rich formatting.

    Args:
        level: Log level override. Defaults to LOG_LEVEL env var, or INFO.

    """
    if level is None:
        env_level = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, env_level, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=level <= logging.DEBUG,
            )
        ],
    )
