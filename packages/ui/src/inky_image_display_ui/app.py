"""NiceGUI page registration entry point.

Importing this module registers all ``@ui.page`` routes against NiceGUI's
global app. Call :func:`register_pages` from the FastAPI assembly so the
side effects happen at a deterministic point.
"""

from __future__ import annotations

import logging

from nicegui import ui

from inky_image_display_ui.session import configure, require_api_client
from inky_image_display_ui.views import devices, images, sync_jobs

logger = logging.getLogger(__name__)

__all__ = ["configure", "register_pages", "require_api_client"]


def register_pages() -> None:
    """Register every page route with NiceGUI."""
    images.register()
    devices.register()
    sync_jobs.register()

    @ui.page("/")
    def index() -> None:
        ui.navigate.to("/images")
