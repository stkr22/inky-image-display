"""Landing page: hero band + bento dashboard of tiles from each section."""

from __future__ import annotations

import logging
from typing import Any

from nicegui import ui

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._registry import get_pages
from inky_image_display_ui.views._ui import bento_grid, tile

logger = logging.getLogger(__name__)


def register() -> None:
    """Register the landing page route at ``/``."""

    @ui.page("/")
    async def landing() -> None:
        with frame("/"):
            _render_hero()
            with bento_grid():
                for page in get_pages():
                    if page.tile is None:
                        continue
                    await page.tile()
                await _render_recent_activity()
                _render_quick_actions()


def _render_hero() -> None:
    with ui.column().classes("w-full gap-4").style("padding: 16px 0 8px 0;"):
        ui.label("Inky Image Display").classes("ink-eyebrow")
        ui.label("Your photos, on paper that never sleeps.").classes("ink-h1")
        ui.label(
            "A quiet wall of e-paper, refreshed automatically from your library. "
            "Pick a device, push an image, or let your sync rules do the work."
        ).classes("ink-body ink-muted").style("max-width: 640px;")
        with ui.row().classes("gap-2 mt-2"):
            with ui.link(target="/devices").classes("ink-btn ink-btn-primary"):
                ui.icon("devices")
                ui.label("Open device wall")
            with ui.link(target="/images").classes("ink-btn ink-btn-ghost"):
                ui.icon("image")
                ui.label("Browse images")


async def _render_recent_activity() -> None:
    api = require_api_client()
    try:
        images = await api.list_images(limit=12)
    except ApiError:
        logger.exception("list_images failed on landing recent activity")
        images = []

    # Sort by last_displayed_at desc (None → fall back to created_at) without an extra API call.
    images = sorted(
        images,
        key=lambda img: (img.get("last_displayed_at") or "", img.get("created_at") or ""),
        reverse=True,
    )[:6]

    with tile(span="col-span-12"):
        with ui.row().classes("w-full items-baseline justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("Recent").classes("ink-eyebrow")
                ui.label("Last shown").classes("ink-h3")
            with ui.link(target="/images").classes("ink-nav-link"):
                ui.label("All images →")

        if not images:
            ui.label("No images yet. Upload one to get started.").classes("ink-small")
            return

        strip = (
            ui.element("div")
            .classes("w-full gap-3")
            .style("display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));")
        )
        with strip:
            for image in images:
                _thumb(image)


def _thumb(image: dict[str, Any]) -> None:
    storage_path = image["storage_path"]
    title = image.get("title") or storage_path.split("/")[-1]
    image_id = image["id"]
    with ui.link(target=f"/images/{image_id}").classes("ink-thumb"):
        ui.image(f"/media/{storage_path}").classes("w-full aspect-square object-cover").props("loading=lazy")
        ui.label(title).classes("ink-small").style(
            "padding: 6px 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
        )


def _render_quick_actions() -> None:
    with tile(span="col-span-12"):
        with ui.column().classes("gap-0"):
            ui.label("Get started").classes("ink-eyebrow")
            ui.label("Quick actions").classes("ink-h3")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            _action_card(
                icon="upload",
                title="Upload an image",
                hint="Add a photo to your library",
                target="/images/new",
            )
            _action_card(
                icon="auto_awesome",
                title="Generate an image",
                hint="One-off AI image via Gemini",
                target="/genai",
            )
            _action_card(
                icon="sync",
                title="New sync job",
                hint="Pull from Immich automatically",
                target="/sync-jobs/new",
            )
            _action_card(
                icon="devices",
                title="Manage devices",
                hint="Choose what each display shows",
                target="/devices",
            )


def _action_card(*, icon: str, title: str, hint: str, target: str) -> None:
    with ui.link(target=target).classes("ink-action-card"):
        with ui.element("div").classes("ink-action-icon"):
            ui.icon(icon)
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(title).classes("text-sm").style("font-weight: 500;")
            ui.label(hint).classes("ink-small").style("white-space: nowrap; overflow: hidden; text-overflow: ellipsis;")


__all__ = ["register"]
