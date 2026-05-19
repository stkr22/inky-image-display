"""App-wide settings view.

Single page exposing operator-tunable values. Currently just the global
default refresh interval used as the fallback when a device or grid has
no per-entity override.
"""

from __future__ import annotations

from nicegui import ui

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import split_hours_minutes
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame


def register() -> None:
    """Register the settings route."""

    @ui.page("/settings")
    async def settings_page() -> None:
        with frame("/settings"):
            await _render()


async def _render() -> None:
    api = require_api_client()

    with ui.row().classes("w-full items-end justify-between"), ui.column().classes("gap-0"):
        ui.label("Configuration").classes("ink-eyebrow")
        ui.label("Settings").classes("ink-h2")

    ui.label(
        "Operator-tunable values. Changes apply on the next refresh tick —"
        " devices already scheduled keep their current slot."
    ).classes("ink-small")

    try:
        current = await api.get_app_settings()
    except ApiError as exc:
        ui.notify(f"Failed to load settings: {exc.detail or exc}", type="negative")
        return

    seconds = int(current.get("default_refresh_seconds") or 0)
    hours, minutes = split_hours_minutes(seconds)

    with ui.card().style("padding: 20px; gap: 12px; max-width: 480px;"):
        ui.label("Default refresh interval").classes("ink-h3")
        ui.label(
            "Used for devices and grids that have 'Use default interval' enabled. Range: 1 minute to 1 week."
        ).classes("ink-small")
        with ui.row().classes("w-full gap-3"):
            hours_input = ui.number("Hours", value=hours, min=0, step=1).props("outlined").classes("flex-1")
            minutes_input = (
                ui.number("Minutes", value=minutes, min=0, max=59, step=1).props("outlined").classes("flex-1")
            )

        async def save() -> None:
            total = int(hours_input.value or 0) * 3600 + int(minutes_input.value or 0) * 60
            if total <= 0:
                ui.notify("Pick at least 1 minute.", type="warning")
                return
            try:
                await api.update_app_settings({"default_refresh_seconds": total})
            except ApiError as exc:
                ui.notify(f"Update failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Default refresh interval updated", type="positive")

        with ui.row().classes("w-full justify-end"):
            ui.button("Save", icon="save", on_click=save).props("unelevated color=primary")
