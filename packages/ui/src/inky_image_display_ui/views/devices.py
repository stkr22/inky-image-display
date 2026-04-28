"""Devices view: cards for each device with next/display/clear actions."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import ui

from inky_image_display_ui.api_client import ApiError, DeviceNotConnectedError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame

logger = logging.getLogger(__name__)


def register() -> None:
    """Register the devices route."""

    @ui.page("/devices")
    async def devices_page() -> None:
        with frame("/devices"):
            await _render()


async def _render() -> None:
    api = require_api_client()

    with ui.row().classes("w-full items-center"):
        ui.label("Devices").classes("text-2xl font-medium")
        ui.space()
        refresh_button = ui.button(icon="refresh").props("flat round").tooltip("Refresh")

    container = ui.column().classes("w-full gap-3")

    async def reload() -> None:
        try:
            devices = await api.list_devices()
        except ApiError as exc:
            ui.notify(f"Failed to load devices: {exc.detail or exc}", type="negative")
            return
        container.clear()
        with container:
            if not devices:
                ui.label("No devices registered yet.").classes("italic text-gray-500")
                return
            for device in devices:
                await _render_device(api, device, reload)

    refresh_button.on_click(reload)
    await reload()


async def _render_device(api: Any, device: dict[str, Any], on_changed: Any) -> None:  # noqa: PLR0915
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

    with ui.card().classes("w-full"):
        with ui.row().classes("w-full gap-4 flex-wrap md:flex-nowrap items-start"):
            with ui.column().classes("gap-1 w-full md:w-[280px]"):
                if current_image:
                    ui.image(f"/media/{current_image['storage_path']}").classes(
                        "w-full max-h-[180px] object-contain rounded bg-gray-100"
                    )
                    ui.label(current_image.get("title") or current_image["storage_path"]).classes("text-xs truncate")
                else:
                    with ui.element("div").classes(
                        "w-full h-[160px] flex items-center justify-center bg-gray-100 rounded"
                    ):
                        ui.label("No image displayed").classes("italic text-gray-500")

            with ui.column().classes("flex-1 min-w-0 gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(device_id).classes("text-lg font-medium")
                    badge_color = "positive" if is_online else "grey"
                    ui.badge("ONLINE" if is_online else "OFFLINE", color=badge_color)
                ui.label(device.get("room") or "(no room)").classes("text-xs text-gray-500")
                ui.label(
                    f"{device['display_width']}x{device['display_height']} {device['display_orientation']} "
                    f"· {device.get('display_model', '?')}"
                ).classes("text-xs")
                ui.label(f"Displayed since: {format_datetime(device.get('displayed_since'))}").classes("text-xs")
                ui.label(f"Next scheduled: {format_datetime(device.get('scheduled_next_at'))}").classes("text-xs")

        with ui.row().classes("w-full gap-2 flex-wrap pt-2"):
            next_btn = ui.button("Next", icon="skip_next", on_click=do_next).props("color=primary")
            choose_btn = ui.button("Choose image…", icon="image_search", on_click=do_choose).props("flat")
            clear_btn = ui.button("Clear", icon="clear", on_click=do_clear).props("flat color=negative")
            for btn in (next_btn, choose_btn, clear_btn):
                btn.set_enabled(is_online)


async def _open_image_picker(api: Any, device: dict[str, Any], *, on_selected: Any) -> None:
    is_portrait = device["display_orientation"] == "portrait"
    if is_portrait:
        target_w, target_h = device["display_height"], device["display_width"]
    else:
        target_w, target_h = device["display_width"], device["display_height"]
    try:
        images = await api.list_images(is_portrait=is_portrait, limit=100)
    except ApiError as exc:
        ui.notify(f"Failed to list images: {exc.detail or exc}", type="negative")
        return
    matches = [
        img for img in images if img.get("original_width") == target_w and img.get("original_height") == target_h
    ]

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
        ui.label(f"Choose image for {device['device_id']}").classes("text-lg font-medium")
        if not matches:
            ui.label("No images match this device's exact dimensions.").classes("italic text-gray-500")
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

                    with (
                        ui.card().tight().classes("cursor-pointer overflow-hidden").on("click", lambda _e, p=pick: p())
                    ):
                        ui.image(f"/media/{image['storage_path']}").classes("w-full aspect-square object-cover")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Close", on_click=dialog.close).props("flat")

    dialog.open()


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("color=primary")
    result = await dialog
    return bool(result)
