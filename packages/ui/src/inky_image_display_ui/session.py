"""Module-level holder for the shared :class:`ApiClient`.

NiceGUI page handlers run as plain async functions, so a single configured
client instance suffices — no per-page session lookup is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inky_image_display_ui.api_client import ApiClient

_api_client: ApiClient | None = None


def configure(*, api_client: ApiClient) -> None:
    """Register the shared :class:`ApiClient` used by every request."""
    global _api_client  # noqa: PLW0603
    _api_client = api_client


def require_api_client() -> ApiClient:
    """Return the configured :class:`ApiClient` or raise a descriptive error."""
    if _api_client is None:
        msg = "ApiClient is not configured; call inky_image_display_ui.session.configure() first."
        raise RuntimeError(msg)
    return _api_client
