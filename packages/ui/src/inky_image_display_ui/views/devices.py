"""Devices view: cards for each device with next/display/clear actions."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import flet as ft

from inky_image_display_ui.api_client import ApiError, DeviceNotConnectedError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import get_api_client

if TYPE_CHECKING:
    from inky_image_display_ui.api_client import ApiClient

logger = logging.getLogger(__name__)


async def build(page: ft.Page) -> ft.Control:
    """Build the devices view, with one card per registered device."""
    api = get_api_client(page)
    container = ft.Column(expand=True, spacing=12, scroll=ft.ScrollMode.AUTO)

    async def reload() -> None:
        try:
            devices = await api.list_devices()
        except ApiError as exc:
            _snack(page, f"Failed to load devices: {exc.detail or exc}")
            return
        container.controls.clear()
        if not devices:
            container.controls.append(ft.Text("No devices registered yet.", italic=True))
        else:
            for device in devices:
                container.controls.append(await _device_card(page, api, device, reload))
        page.update()

    refresh_button = ft.IconButton(
        icon=ft.Icons.REFRESH,
        tooltip="Refresh",
        on_click=lambda _e: asyncio.create_task(reload()),
    )

    await reload()

    return ft.Column(
        [
            ft.Row([ft.Text("Devices", size=22, weight=ft.FontWeight.BOLD), ft.Container(expand=True), refresh_button]),
            container,
        ],
        expand=True,
    )


async def _device_card(
    page: ft.Page,
    api: ApiClient,
    device: dict[str, Any],
    on_changed: Any,
) -> ft.Control:
    device_id: str = device["device_id"]
    is_online: bool = bool(device.get("is_online"))
    current_image = None
    current_image_id = device.get("current_image_id")
    if current_image_id:
        try:
            current_image = await api.get_image(UUID(current_image_id))
        except ApiError:
            current_image = None

    status_pill = ft.Container(
        content=ft.Text("ONLINE" if is_online else "OFFLINE", size=11, weight=ft.FontWeight.BOLD),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        bgcolor=ft.Colors.GREEN if is_online else ft.Colors.OUTLINE_VARIANT,
        border_radius=10,
    )

    current_preview: ft.Control
    if current_image:
        current_preview = ft.Column(
            [
                ft.Image(
                    src=f"/media/{current_image['storage_path']}",
                    fit=ft.BoxFit.CONTAIN,
                    height=160,
                    width=260,
                ),
                ft.Text(current_image.get("title") or current_image["storage_path"], size=12),
            ],
            tight=True,
        )
    else:
        current_preview = ft.Container(
            ft.Text("No image displayed", italic=True),
            height=160,
            width=260,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=6,
        )

    async def do_next() -> None:
        try:
            result = await api.next_image(device_id)
        except DeviceNotConnectedError:
            _snack(page, f"{device_id} is offline — command dropped")
            return
        except ApiError as exc:
            _snack(page, f"Next failed: {exc.detail or exc}")
            return
        _snack(page, f"Showing: {result.get('title') or result.get('image_id')}")
        await on_changed()

    async def do_clear() -> None:
        if not await _confirm(page, f"Clear the display on {device_id}?"):
            return
        try:
            await api.clear_device(device_id)
        except DeviceNotConnectedError:
            _snack(page, f"{device_id} is offline — command dropped")
            return
        except ApiError as exc:
            _snack(page, f"Clear failed: {exc.detail or exc}")
            return
        _snack(page, f"{device_id} cleared")
        await on_changed()

    async def do_choose() -> None:
        await _open_image_picker(page, api, device, on_selected=do_display)

    async def do_display(image_id: UUID) -> None:
        try:
            await api.display_image(device_id, image_id)
        except DeviceNotConnectedError:
            _snack(page, f"{device_id} is offline — command dropped")
            return
        except ApiError as exc:
            _snack(page, f"Display failed: {exc.detail or exc}")
            return
        _snack(page, f"Sent image to {device_id}")
        await on_changed()

    actions = ft.Row(
        [
            ft.FilledButton(
                "Next",
                icon=ft.Icons.SKIP_NEXT,
                on_click=lambda _e: asyncio.create_task(do_next()),
                disabled=not is_online,
            ),
            ft.OutlinedButton(
                "Choose image…",
                icon=ft.Icons.IMAGE_SEARCH,
                on_click=lambda _e: asyncio.create_task(do_choose()),
                disabled=not is_online,
            ),
            ft.OutlinedButton(
                "Clear",
                icon=ft.Icons.CLEAR,
                on_click=lambda _e: asyncio.create_task(do_clear()),
                disabled=not is_online,
            ),
        ]
    )

    meta = ft.Column(
        [
            ft.Row([ft.Text(device_id, size=18, weight=ft.FontWeight.BOLD), status_pill]),
            ft.Text(device.get("room") or "(no room)", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(
                f"{device['display_width']}x{device['display_height']} {device['display_orientation']} - "
                f"{device.get('display_model', '?')}",
                size=12,
            ),
            ft.Text(f"Displayed since: {format_datetime(device.get('displayed_since'))}", size=12),
            ft.Text(f"Next scheduled: {format_datetime(device.get('scheduled_next_at'))}", size=12),
        ],
        tight=True,
    )

    return ft.Card(
        content=ft.Container(
            ft.Column(
                [
                    ft.Row([current_preview, ft.Container(meta, expand=True, padding=ft.padding.only(left=16))]),
                    actions,
                ],
                tight=True,
            ),
            padding=16,
        )
    )


async def _open_image_picker(
    page: ft.Page,
    api: ApiClient,
    device: dict[str, Any],
    *,
    on_selected: Any,
) -> None:
    is_portrait = device["display_orientation"] == "portrait"
    target_w = device["display_width"]
    target_h = device["display_height"]
    try:
        images = await api.list_images(is_portrait=is_portrait, limit=100)
    except ApiError as exc:
        _snack(page, f"Failed to list images: {exc.detail or exc}")
        return
    # Exact dimension match only
    images = [img for img in images if img.get("original_width") == target_w and img.get("original_height") == target_h]

    grid = ft.GridView(expand=True, max_extent=160, child_aspect_ratio=1.0, spacing=6, run_spacing=6)

    async def pick(image_id: UUID) -> None:
        page.pop_dialog()
        await on_selected(image_id)

    for image in images:
        image_uuid = UUID(image["id"])

        def _wrap(uuid: UUID) -> Any:
            return lambda _e: asyncio.create_task(pick(uuid))

        grid.controls.append(
            ft.GestureDetector(
                on_tap=_wrap(image_uuid),
                content=ft.Image(
                    src=f"/media/{image['storage_path']}",
                    fit=ft.BoxFit.COVER,
                    width=160,
                    height=160,
                    border_radius=4,
                ),
            )
        )

    body: ft.Control = grid if images else ft.Text("No images match this device's exact dimensions.", italic=True)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Choose image for {device['device_id']}"),
        content=ft.Container(body, height=420, width=640),
        actions=[ft.TextButton("Close", on_click=lambda _e: page.pop_dialog())],
    )
    page.show_dialog(dialog)


async def _confirm(page: ft.Page, message: str) -> bool:
    """Open a modal confirm dialog and await the user's choice."""
    result: dict[str, bool] = {"value": False}
    event = asyncio.Event()

    def close(value: bool) -> None:
        result["value"] = value
        event.set()
        page.pop_dialog()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirm"),
        content=ft.Text(message),
        actions=[
            ft.TextButton("Cancel", on_click=lambda _e: close(False)),
            ft.FilledButton("Confirm", on_click=lambda _e: close(True)),
        ],
    )
    page.show_dialog(dialog)
    await event.wait()
    return result["value"]


def _snack(page: ft.Page, message: str) -> None:
    page.show_dialog(ft.SnackBar(content=ft.Text(message), duration=3000))
