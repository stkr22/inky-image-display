"""Shared Flet session helpers.

This module is split from :mod:`inky_image_display_ui.app` so that the view
modules can look up the configured :class:`ApiClient` without creating a circular
import (``app`` imports ``views``; ``views`` import this module).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import flet as ft

    from inky_image_display_ui.api_client import ApiClient

_api_client: ApiClient | None = None


def configure(*, api_client: ApiClient) -> None:
    """Register the shared :class:`ApiClient` used by every Flet session."""
    global _api_client  # noqa: PLW0603
    _api_client = api_client


def require_api_client() -> ApiClient:
    """Return the configured :class:`ApiClient` or raise a descriptive error."""
    if _api_client is None:
        msg = "ApiClient is not configured; call inky_image_display_ui.session.configure() first."
        raise RuntimeError(msg)
    return _api_client


def get_api_client(page: ft.Page) -> ApiClient:
    """Retrieve the shared :class:`ApiClient` stored on the page session."""
    client = page.session.store.get("api_client")
    if client is None:  # pragma: no cover - defensive
        msg = "ApiClient missing from page session"
        raise RuntimeError(msg)
    return client
