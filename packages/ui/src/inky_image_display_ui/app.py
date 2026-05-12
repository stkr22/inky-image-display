"""NiceGUI page registration entry point.

Importing this module registers all ``@ui.page`` routes against NiceGUI's
global app. Call :func:`register_pages` from the FastAPI assembly so the
side effects happen at a deterministic point.
"""

from __future__ import annotations

import logging

from inky_image_display_ui.session import configure, require_api_client
from inky_image_display_ui.views import landing
from inky_image_display_ui.views._registry import get_pages

logger = logging.getLogger(__name__)

__all__ = ["configure", "register_pages", "require_api_client"]


def register_pages() -> None:
    """Register every page route with NiceGUI.

    Section pages come from the central registry so adding a new view = one
    new ``PageSpec``. The landing page owns ``/`` and is registered last so
    its tiles can pull from already-registered sections.
    """
    for page in get_pages():
        page.register()
    landing.register()
