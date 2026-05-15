"""Unified jobs listing — Immich + Gemini in one tabbed page.

The per-source create/edit forms still live in their own modules
(:mod:`sync_jobs`, :mod:`gemini_jobs`); this view is purely the combined list
and the landing tile so end-users see one "Jobs" section instead of two.
"""

from __future__ import annotations

import logging
from typing import Any

from nicegui import ui

from inky_image_display_ui.api_client import ApiClient, ApiError
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views import gemini_jobs as gemini_view
from inky_image_display_ui.views import sync_jobs as immich_view
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._ui import stat
from inky_image_display_ui.views._ui import tile as bento_tile

logger = logging.getLogger(__name__)

_SOURCES = ("immich", "gemini")


def register() -> None:
    """Register the unified /jobs route."""

    @ui.page("/jobs")
    async def jobs_page(tab: str = "immich") -> None:
        with frame("/jobs"):
            await _render(tab if tab in _SOURCES else "immich")


async def _render(initial: str) -> None:
    api = require_api_client()
    profile_map = await _profile_map(api)

    # Mutable state shared between the tab control, the "New job" button,
    # and the body renderer. Rebuilding from scratch on every tab change
    # avoids Quasar's tab-panel DOM lifecycle (which destroys hidden panels
    # and would blank out our list after a couple of toggles).
    state: dict[str, str] = {"active": initial}

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Automations").classes("ink-eyebrow")
            ui.label("Jobs").classes("ink-h2")
        new_button = ui.button("New Immich job", icon="add").props("color=primary unelevated")

    def update_new_button() -> None:
        if state["active"] == "gemini":
            new_button.text = "New Gemini job"
            new_button.on_click(lambda: ui.navigate.to("/gemini-jobs/new"))
        else:
            new_button.text = "New Immich job"
            new_button.on_click(lambda: ui.navigate.to("/sync-jobs/new"))

    update_new_button()

    tabs_style = "border-bottom: 1px solid var(--ink-border); padding-bottom: 8px;"
    with ui.row().classes("w-full gap-2 items-center").style(tabs_style):
        immich_btn = ui.button("Immich", icon="sync").props("flat")
        gemini_btn = ui.button("Gemini", icon="bolt").props("flat")

    body = ui.column().classes("w-full gap-2")

    def style_tab_buttons() -> None:
        for source, btn in (("immich", immich_btn), ("gemini", gemini_btn)):
            if source == state["active"]:
                btn.props(remove="flat")
                btn.props("unelevated color=primary")
            else:
                btn.props(remove="unelevated color=primary")
                btn.props("flat")

    async def switch(source: str) -> None:
        state["active"] = source
        style_tab_buttons()
        update_new_button()
        await render_list()

    immich_btn.on_click(lambda: switch("immich"))
    gemini_btn.on_click(lambda: switch("gemini"))

    async def render_list() -> None:
        body.clear()
        with body:
            if state["active"] == "gemini":
                await _render_gemini_list(api, profile_map)
            else:
                await _render_immich_list(api, profile_map)

    style_tab_buttons()
    await render_list()


async def _render_immich_list(api: ApiClient, profile_map: dict[str, str]) -> None:
    try:
        jobs = await api.list_sync_jobs()
    except ApiError as exc:
        ui.notify(f"Failed to load Immich jobs: {exc.detail or exc}", type="negative")
        return
    if not jobs:
        ui.label("No Immich sync jobs yet.").classes("italic text-gray-500")
        return
    container = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        container.clear()
        with container:
            fresh = await api.list_sync_jobs()
            for job in fresh:
                immich_view._render_row(api, job, profile_map, reload)

    with container:
        for job in jobs:
            immich_view._render_row(api, job, profile_map, reload)


async def _render_gemini_list(api: ApiClient, profile_map: dict[str, str]) -> None:
    try:
        jobs = await api.list_gemini_jobs()
    except ApiError as exc:
        ui.notify(f"Failed to load Gemini jobs: {exc.detail or exc}", type="negative")
        return
    if not jobs:
        ui.label("No Gemini jobs yet.").classes("italic text-gray-500")
        return
    container = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        container.clear()
        with container:
            fresh = await api.list_gemini_jobs()
            for job in fresh:
                gemini_view._render_row(api, job, profile_map, reload)

    with container:
        for job in jobs:
            gemini_view._render_row(api, job, profile_map, reload)


async def _profile_map(api: ApiClient) -> dict[str, str]:
    try:
        profiles = await api.list_device_profiles()
    except ApiError:
        return {}
    return {p["id"]: p["name"] for p in profiles}


async def tile() -> None:
    """Render the combined Jobs tile counting Immich and Gemini totals."""
    api = require_api_client()
    immich: list[dict[str, Any]] = []
    gemini: list[dict[str, Any]] = []
    try:
        immich = await api.list_sync_jobs()
    except ApiError:
        logger.exception("list_sync_jobs failed on landing tile")
    try:
        gemini = await api.list_gemini_jobs()
    except ApiError:
        logger.exception("list_gemini_jobs failed on landing tile")

    total = len(immich) + len(gemini)
    active = sum(1 for j in immich if j.get("is_active")) + sum(1 for j in gemini if j.get("is_active"))

    with bento_tile(span="col-span-4", href="/jobs"):
        stat(
            label="Jobs",
            value=f"{active}/{total}",
            hint=f"Immich {len(immich)} · Gemini {len(gemini)}",
        )


__all__ = ["register", "tile"]
