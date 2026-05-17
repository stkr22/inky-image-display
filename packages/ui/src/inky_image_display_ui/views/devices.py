"""Devices view: cards for each device with next/display/clear actions."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import ui

from inky_image_display_ui.api_client import ApiError, DeviceNotConnectedError
from inky_image_display_ui.formatting import (
    format_datetime,
    format_interval_seconds,
    format_relative,
    split_hours_minutes,
)
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._ui import badge
from inky_image_display_ui.views._ui import tile as bento_tile

logger = logging.getLogger(__name__)


def register() -> None:
    """Register the devices route."""

    @ui.page("/devices")
    async def devices_page() -> None:
        with frame("/devices"):
            await _render()


async def _render() -> None:
    api = require_api_client()

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Wall").classes("ink-eyebrow")
            ui.label("Devices").classes("ink-h2")
        refresh_button = ui.button(icon="refresh").props("flat round").tooltip("Refresh")

    container = ui.column().classes("w-full gap-3")

    async def reload() -> None:
        try:
            devices = await api.list_devices()
            profiles = await api.list_device_profiles()
        except ApiError as exc:
            ui.notify(f"Failed to load devices: {exc.detail or exc}", type="negative")
            return
        profile_by_id = {p["id"]: p for p in profiles}
        container.clear()
        with container:
            if not devices:
                ui.label("No devices registered yet.").classes("italic text-gray-500")
                return
            for device in devices:
                await _render_device(api, device, profile_by_id, reload)

    refresh_button.on_click(reload)
    await reload()


async def _render_device(  # noqa: PLR0915
    api: Any,
    device: dict[str, Any],
    profile_by_id: dict[str, dict[str, Any]],
    on_changed: Any,
) -> None:
    device_id: str = device["device_id"]
    is_online: bool = bool(device.get("is_online"))

    current_image: dict[str, Any] | None = None
    current_image_id = device.get("current_image_id")
    if current_image_id:
        try:
            current_image = await api.get_image(UUID(current_image_id))
        except ApiError:
            current_image = None

    async def do_next() -> None:
        try:
            result = await api.next_image(device_id)
        except DeviceNotConnectedError:
            ui.notify(f"{device_id} is offline — command dropped", type="warning")
            return
        except ApiError as exc:
            ui.notify(f"Next failed: {exc.detail or exc}", type="negative")
            return
        ui.notify(f"Showing: {result.get('title') or result.get('image_id')}")
        await on_changed()

    async def do_clear() -> None:
        if not await _confirm(f"Clear the display on {device_id}?"):
            return
        try:
            await api.clear_device(device_id)
        except DeviceNotConnectedError:
            ui.notify(f"{device_id} is offline — command dropped", type="warning")
            return
        except ApiError as exc:
            ui.notify(f"Clear failed: {exc.detail or exc}", type="negative")
            return
        ui.notify(f"{device_id} cleared", type="positive")
        await on_changed()

    async def do_display(image_id: UUID) -> None:
        try:
            await api.display_image(device_id, image_id)
        except DeviceNotConnectedError:
            ui.notify(f"{device_id} is offline — command dropped", type="warning")
            return
        except ApiError as exc:
            ui.notify(f"Display failed: {exc.detail or exc}", type="negative")
            return
        ui.notify(f"Sent image to {device_id}", type="positive")
        await on_changed()

    async def do_choose() -> None:
        await _open_image_picker(api, device, on_selected=do_display)

    async def do_schedule() -> None:
        await _open_schedule_dialog(api, device, on_changed)

    with ui.element("div").style(
        "width: 100%; padding: 20px; background: var(--ink-surface);"
        " border: 1px solid var(--ink-border); border-radius: 20px;"
        " box-shadow: 0 1px 2px rgba(11,18,32,0.04); display: flex; flex-direction: column; gap: 16px;"
    ):
        with ui.row().classes("w-full gap-5 flex-wrap md:flex-nowrap items-start"):
            with ui.column().classes("gap-2 w-full md:w-[300px]"):
                if current_image:
                    ui.image(f"/media/{current_image['storage_path']}").classes("ink-device-image").props(
                        "loading=lazy"
                    )
                    ui.label(current_image.get("title") or current_image["storage_path"]).classes("ink-small").style(
                        "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
                    )
                else:
                    with (
                        ui.element("div")
                        .classes("ink-device-image")
                        .style("display: flex; align-items: center; justify-content: center;")
                    ):
                        ui.label("No image displayed").classes("ink-small")

            with ui.column().classes("flex-1 min-w-0 gap-2"):
                with ui.row().classes("items-center gap-3"):
                    ui.label(device_id).classes("ink-h3")
                    badge("Online" if is_online else "Offline", tone="ok" if is_online else "muted")
                ui.label(device.get("room") or "(no room)").classes("ink-small")
                profile_id = device.get("device_profile_id")
                profile = profile_by_id.get(profile_id) if profile_id else None
                profile_summary = (
                    f"{profile['name']} ({profile['width']}x{profile['height']})"
                    if profile is not None
                    else "(unknown profile)"
                )
                ui.label(f"{profile_summary} · {device['display_orientation']}").classes("ink-small")
                ui.label(f"Displayed since {format_datetime(device.get('displayed_since'))}").classes("ink-small")
                next_at = device.get("scheduled_next_at")
                ui.label(f"Next scheduled {format_datetime(next_at)} ({format_relative(next_at)})").classes("ink-small")
                interval_value = device.get("refresh_interval_seconds")
                interval_label = format_interval_seconds(interval_value, default_label="default")
                ui.label(f"Refresh every {interval_label}").classes("ink-small")

        with (
            ui.row()
            .classes("w-full gap-2 flex-wrap")
            .style("border-top: 1px solid var(--ink-border); padding-top: 14px;")
        ):
            next_btn = ui.button("Next", icon="skip_next", on_click=do_next).props("unelevated color=primary")
            choose_btn = ui.button("Choose image", icon="image_search", on_click=do_choose).props("flat")
            # Schedule editing is independent of online state — operators
            # often want to dial cadence on a device that's currently offline.
            ui.button("Schedule", icon="schedule", on_click=do_schedule).props("flat")
            clear_btn = ui.button("Clear", icon="clear", on_click=do_clear).props("flat color=negative")
            for btn in (next_btn, choose_btn, clear_btn):
                btn.set_enabled(is_online)


async def tile() -> None:
    """Render the Devices bento tile on the landing dashboard."""
    api = require_api_client()
    try:
        devices = await api.list_devices()
    except ApiError:
        logger.exception("list_devices failed on landing tile")
        devices = []

    online = sum(1 for d in devices if d.get("is_online"))
    total = len(devices)

    with bento_tile(span="col-span-8", row_span="row-span-2"):
        with ui.row().classes("w-full items-baseline justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("Wall").classes("ink-eyebrow")
                ui.label("Devices").classes("ink-h3")
            ui.label(f"{online}/{total} online").classes("ink-small")

        if not devices:
            ui.label("No devices registered yet.").classes("ink-small")
            return

        strip = (
            ui.element("div")
            .classes("w-full gap-3 mt-1")
            .style("display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));")
        )
        with strip:
            for device in devices[:6]:
                await _render_mini_device(api, device)


async def _render_mini_device(api: Any, device: dict[str, Any]) -> None:
    current_image: dict[str, Any] | None = None
    current_image_id = device.get("current_image_id")
    if current_image_id:
        try:
            current_image = await api.get_image(UUID(current_image_id))
        except ApiError:
            current_image = None

    with ui.link(target="/devices").classes("ink-device-card"):
        if current_image:
            ui.image(f"/media/{current_image['storage_path']}").classes("ink-device-image").props("loading=lazy")
        else:
            with (
                ui.element("div")
                .classes("ink-device-image")
                .style("display: flex; align-items: center; justify-content: center;")
            ):
                ui.label("—").classes("ink-small")
        with ui.column().classes("gap-1 p-3"):
            with ui.row().classes("items-center justify-between"):
                ui.label(device["device_id"]).classes("text-sm").style("font-weight: 500;")
                badge("●", tone="ok" if device.get("is_online") else "muted")
            ui.label(device.get("room") or "—").classes("ink-small").style(
                "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
            )


async def _open_image_picker(api: Any, device: dict[str, Any], *, on_selected: Any) -> None:
    is_portrait = device["display_orientation"] == "portrait"
    try:
        profiles = await api.list_device_profiles()
    except ApiError as exc:
        ui.notify(f"Failed to load device profiles: {exc.detail or exc}", type="negative")
        return
    profile = next((p for p in profiles if p["id"] == device.get("device_profile_id")), None)
    if profile is None:
        ui.notify("Device profile not found", type="negative")
        return
    if is_portrait:
        target_w, target_h = profile["height"], profile["width"]
    else:
        target_w, target_h = profile["width"], profile["height"]
    try:
        images = await api.list_images(is_portrait=is_portrait, limit=100)
    except ApiError as exc:
        ui.notify(f"Failed to list images: {exc.detail or exc}", type="negative")
        return
    matches = [
        img for img in images if img.get("original_width") == target_w and img.get("original_height") == target_h
    ]

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl").style("padding: 24px;"):
        with ui.column().classes("gap-0 mb-2"):
            ui.label("Choose").classes("ink-eyebrow")
            ui.label(f"Image for {device['device_id']}").classes("ink-h3")
        if not matches:
            ui.label("No images match this device's exact dimensions.").classes("ink-small")
        else:
            grid = (
                ui.element("div")
                .classes("grid w-full gap-2")
                .style("grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));")
            )
            with grid:
                for image in matches:
                    image_uuid = UUID(image["id"])

                    async def pick(uuid: UUID = image_uuid) -> None:
                        dialog.close()
                        await on_selected(uuid)

                    with ui.element("div").classes("ink-thumb").on("click", lambda _e, p=pick: p()):
                        ui.image(f"/media/{image['storage_path']}").classes("w-full aspect-square object-cover").props(
                            "loading=lazy"
                        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Close", on_click=dialog.close).props("flat")

    dialog.open()


async def _open_schedule_dialog(api: Any, device: dict[str, Any], on_done: Any) -> None:
    """Edit the rotation cadence for one device.

    "Use default" sends ``clear_refresh_interval=True`` so the server
    resets the override to ``NULL`` rather than ambiguously storing 0.
    """
    current = device.get("refresh_interval_seconds")
    hours, minutes = split_hours_minutes(current)

    with ui.dialog() as dialog, ui.card().style("padding: 20px; min-width: 360px; gap: 12px;"):
        ui.label(f"Schedule for {device['device_id']}").classes("ink-h3")
        use_default = ui.switch("Use default interval", value=current is None)
        hours_input = ui.number("Hours", value=hours, min=0, step=1).props("outlined")
        minutes_input = ui.number("Minutes", value=minutes, min=0, max=59, step=1).props("outlined")

        def sync_enabled() -> None:
            enabled = not use_default.value
            hours_input.set_enabled(enabled)
            minutes_input.set_enabled(enabled)

        use_default.on_value_change(lambda _e: sync_enabled())
        sync_enabled()

        ui.label("Rotation cadence applied after the next refresh tick.").classes("ink-small")

        async def submit() -> None:
            if use_default.value:
                payload: dict[str, Any] = {"clear_refresh_interval": True}
            else:
                total_seconds = int(hours_input.value or 0) * 3600 + int(minutes_input.value or 0) * 60
                if total_seconds <= 0:
                    ui.notify("Pick at least 1 minute, or switch to default.", type="warning")
                    return
                payload = {"refresh_interval_seconds": total_seconds}
            try:
                await api.update_device(device["device_id"], payload)
            except ApiError as exc:
                ui.notify(f"Update failed: {exc.detail or exc}", type="negative")
                return
            dialog.close()
            ui.notify("Schedule updated", type="positive")
            await on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Save", on_click=submit).props("unelevated color=primary")
    dialog.open()


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card().style("padding: 20px; gap: 12px; min-width: 320px;"):
        ui.label(message).classes("ink-body")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("unelevated color=primary")
    result = await dialog
    return bool(result)
