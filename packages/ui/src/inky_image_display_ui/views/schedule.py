"""Schedule view: global chronological queue of upcoming refreshes.

A single page that polls ``GET /api/schedule/upcoming`` and renders the
merged device + grid queue ordered by ``scheduled_next_at``. Lets users
see at a glance which device/grid is up next and how soon.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import format_datetime, format_interval_seconds, format_relative
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame

# Polling cadence for the dashboard. Tuned to match the rotation loop's
# 30-second tick so the queue can shift at most one position between
# refreshes — slower would mean stale "in 0s" labels.
_POLL_INTERVAL_SECONDS = 15
_DEFAULT_LIMIT = 20


def register() -> None:
    """Register the schedule route."""

    @ui.page("/schedule")
    async def schedule_page() -> None:
        with frame("/schedule"):
            await _render()


async def _render() -> None:
    api = require_api_client()

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Upcoming").classes("ink-eyebrow")
            ui.label("Schedule").classes("ink-h2")
        refresh_button = ui.button(icon="refresh").props("flat round").tooltip("Refresh")

    ui.label(
        "Ordered by next refresh time. Devices currently driven by a grid are hidden — the grid entry represents them."
    ).classes("ink-small")

    container = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        try:
            entries = await api.get_schedule_upcoming(limit=_DEFAULT_LIMIT)
        except ApiError as exc:
            ui.notify(f"Failed to load schedule: {exc.detail or exc}", type="negative")
            return
        container.clear()
        with container:
            if not entries:
                ui.label("Nothing scheduled yet.").classes("italic text-gray-500")
                return
            for index, entry in enumerate(entries, start=1):
                _render_entry(index, entry)

    refresh_button.on_click(reload)
    await reload()
    # Auto-refresh so the dashboard doesn't go stale while the user watches.
    ui.timer(_POLL_INTERVAL_SECONDS, reload)


def _render_entry(position: int, entry: dict[str, Any]) -> None:
    kind = entry.get("kind", "device")
    icon = "devices" if kind == "device" else "grid_view"
    target = "/devices" if kind == "device" else "/grids"
    next_at = entry.get("scheduled_next_at")
    interval_label = format_interval_seconds(
        entry.get("effective_interval_seconds"),
        default_label="default",
    )

    with (
        ui.link(target=target)
        .classes("w-full no-underline")
        .style(
            "color: inherit; padding: 14px 16px; background: var(--ink-surface);"
            " border: 1px solid var(--ink-border); border-radius: 14px;"
            " display: flex; gap: 16px; align-items: center;"
        )
    ):
        ui.label(f"#{position}").style("font-variant-numeric: tabular-nums; min-width: 32px; opacity: 0.6;")
        ui.icon(icon).style("opacity: 0.7;")
        with ui.column().classes("gap-0 flex-1 min-w-0"):
            ui.label(entry["name"]).classes("ink-body").style(
                "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
            )
            ui.label(f"{kind} · every {interval_label}").classes("ink-small")
        with ui.column().classes("gap-0 items-end"):
            ui.label(format_relative(next_at)).classes("ink-body").style("font-weight: 500;")
            ui.label(format_datetime(next_at)).classes("ink-small")
