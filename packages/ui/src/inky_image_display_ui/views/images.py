"""Images view: gallery, upload, detail/edit, delete."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import flet as ft

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import get_api_client

if TYPE_CHECKING:
    from inky_image_display_ui.api_client import ApiClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 30


async def build(page: ft.Page) -> ft.Control:
    """Build the images gallery view, including filters, grid, and upload FAB."""
    api = get_api_client(page)
    state: dict[str, Any] = {"offset": 0, "source_name": None, "is_portrait": None}

    source_filter = ft.Dropdown(
        label="Source",
        width=180,
        options=[
            ft.dropdown.Option(key="", text="All"),
            ft.dropdown.Option(key="manual", text="manual"),
            ft.dropdown.Option(key="immich", text="immich"),
        ],
    )
    portrait_switch = ft.Switch(label="Portrait only", value=False)
    prev_button = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="Previous page")
    next_button = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="Next page")
    page_label = ft.Text("")

    grid = ft.GridView(
        expand=True,
        max_extent=260,
        child_aspect_ratio=1.0,
        spacing=8,
        run_spacing=8,
    )

    async def reload() -> None:
        try:
            rows = await api.list_images(
                source_name=state["source_name"],
                is_portrait=state["is_portrait"],
                limit=_PAGE_SIZE,
                offset=state["offset"],
            )
        except ApiError as exc:
            logger.exception("list_images failed")
            _snack(page, f"Failed to load images: {exc.detail or exc}")
            return
        _render_grid(page, grid, rows, api, reload)
        offset = state["offset"]
        page_label.value = f"Showing {offset + 1}-{offset + len(rows)}"
        prev_button.disabled = offset == 0
        next_button.disabled = len(rows) < _PAGE_SIZE
        page.update()

    async def on_filter_change() -> None:
        state["source_name"] = source_filter.value or None
        state["is_portrait"] = True if portrait_switch.value else None
        state["offset"] = 0
        await reload()

    async def on_prev() -> None:
        state["offset"] = max(0, state["offset"] - _PAGE_SIZE)
        await reload()

    async def on_next() -> None:
        state["offset"] += _PAGE_SIZE
        await reload()

    source_filter.on_select = lambda _e: asyncio.create_task(on_filter_change())
    portrait_switch.on_change = lambda _e: asyncio.create_task(on_filter_change())
    prev_button.on_click = lambda _e: asyncio.create_task(on_prev())
    next_button.on_click = lambda _e: asyncio.create_task(on_next())

    upload_fab = ft.FloatingActionButton(
        icon=ft.Icons.UPLOAD,
        tooltip="Upload image",
        on_click=lambda _e: _open_upload_dialog(page, on_uploaded=reload),
    )

    await reload()

    return ft.Column(
        [
            ft.Row([source_filter, portrait_switch, ft.Container(expand=True), prev_button, page_label, next_button]),
            ft.Container(grid, expand=True),
            ft.Row([ft.Container(expand=True), upload_fab]),
        ],
        expand=True,
    )


def _render_grid(
    page: ft.Page,
    grid: ft.GridView,
    rows: list[dict[str, Any]],
    api: ApiClient,
    on_changed: Any,
) -> None:
    grid.controls.clear()
    for image in rows:
        grid.controls.append(_tile(page, image, api, on_changed))


def _tile(page: ft.Page, image: dict[str, Any], api: ApiClient, on_changed: Any) -> ft.Control:
    storage_path = image["storage_path"]
    title = image.get("title") or storage_path.split("/")[-1]
    overlay = ft.Container(
        content=ft.Text(title, color=ft.Colors.WHITE, size=12),
        padding=6,
        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        alignment=ft.Alignment.BOTTOM_LEFT,
    )
    return ft.GestureDetector(
        on_tap=lambda _e: _open_detail(page, image, api, on_changed),
        content=ft.Stack(
            [
                ft.Image(
                    src=f"/media/{storage_path}",
                    fit=ft.BoxFit.COVER,
                    width=260,
                    height=260,
                    border_radius=6,
                ),
                overlay,
            ]
        ),
    )


def _open_detail(page: ft.Page, image: dict[str, Any], api: ApiClient, on_changed: Any) -> None:
    title_field = ft.TextField(label="Title", value=image.get("title") or "", width=420)
    description_field = ft.TextField(
        label="Description", value=image.get("description") or "", multiline=True, min_lines=2, max_lines=5, width=420
    )
    author_field = ft.TextField(label="Author", value=image.get("author") or "", width=420)
    tags_field = ft.TextField(label="Tags (comma-separated)", value=image.get("tags") or "", width=420)
    duration_field = ft.TextField(
        label="Display duration (seconds)",
        value=str(image.get("display_duration_seconds") or 600),
        width=220,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    priority_slider = ft.Slider(
        min=1, max=10, divisions=9, value=float(image.get("priority") or 5), label="Priority: {value}"
    )

    async def save() -> None:
        try:
            duration = int(duration_field.value or 600)
        except ValueError:
            _snack(page, "Duration must be an integer")
            return
        body = {
            "title": title_field.value or None,
            "description": description_field.value or None,
            "author": author_field.value or None,
            "tags": tags_field.value or None,
            "display_duration_seconds": duration,
            "priority": int(priority_slider.value or 5),
        }
        try:
            await api.update_image(UUID(image["id"]), body)
        except ApiError as exc:
            _snack(page, f"Update failed: {exc.detail or exc}")
            return
        _snack(page, "Saved")
        page.pop_dialog()
        await on_changed()

    async def delete() -> None:
        confirmed = await _confirm(page, f"Delete image '{image.get('title') or image['id']}'?")
        if not confirmed:
            return
        try:
            await api.delete_image(UUID(image["id"]))
        except ApiError as exc:
            _snack(page, f"Delete failed: {exc.detail or exc}")
            return
        _snack(page, "Deleted")
        page.pop_dialog()
        await on_changed()

    created = format_datetime(image.get("created_at"))
    last_displayed = format_datetime(image.get("last_displayed_at"))
    dims = f"{image.get('original_width') or '?'}x{image.get('original_height') or '?'}"

    source_url = image.get("source_url")
    source_row: ft.Control
    if source_url and source_url.startswith(("http://", "https://")):
        source_row = ft.Row(
            [
                ft.Text("Source URL:", size=12),
                ft.TextButton(
                    source_url,
                    url=source_url,
                    style=ft.ButtonStyle(padding=0),
                ),
            ],
            tight=True,
            wrap=True,
        )
    else:
        source_row = ft.Text(f"Source URL: {source_url or '-'}", size=12, selectable=True)

    meta_lines: list[ft.Control] = [
        ft.Text(f"ID: {image['id']}", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT),
        ft.Text(f"Source: {image.get('source_name', '?')}", size=12),
    ]
    if image.get("source_id"):
        meta_lines.append(ft.Text(f"Source ID: {image['source_id']}", size=12, selectable=True))
    if image.get("sync_job_name"):
        meta_lines.append(ft.Text(f"Sync job: {image['sync_job_name']}", size=12))
    meta_lines.extend(
        [
            source_row,
            ft.Text(f"Dimensions: {dims}", size=12),
            ft.Text(f"Created: {created}", size=12),
            ft.Text(f"Last displayed: {last_displayed}", size=12),
        ]
    )

    meta = ft.Column(meta_lines, tight=True)

    sheet = ft.BottomSheet(
        ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Image(
                                src=f"/media/{image['storage_path']}",
                                fit=ft.BoxFit.CONTAIN,
                                height=320,
                                width=480,
                            ),
                            ft.Container(meta, padding=12, expand=True),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    title_field,
                    description_field,
                    author_field,
                    tags_field,
                    ft.Row([duration_field, ft.Container(priority_slider, expand=True)]),
                    ft.Row(
                        [
                            ft.TextButton("Close", on_click=lambda _e: page.pop_dialog()),
                            ft.Container(expand=True),
                            ft.OutlinedButton(
                                "Delete", icon=ft.Icons.DELETE, on_click=lambda _e: asyncio.create_task(delete())
                            ),
                            ft.FilledButton(
                                "Save", icon=ft.Icons.SAVE, on_click=lambda _e: asyncio.create_task(save())
                            ),
                        ]
                    ),
                ],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=16,
        ),
        open=True,
    )
    page.show_dialog(sheet)


def _open_upload_dialog(page: ft.Page, *, on_uploaded: Any) -> None:  # noqa: PLR0915
    api = get_api_client(page)
    title_field = ft.TextField(label="Title")
    description_field = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4)
    author_field = ft.TextField(label="Author")
    tags_field = ft.TextField(label="Tags (comma-separated)")
    duration_field = ft.TextField(label="Display duration (seconds)", value="600", keyboard_type=ft.KeyboardType.NUMBER)
    priority_slider = ft.Slider(min=1, max=10, divisions=9, value=5, label="Priority: {value}")
    portrait_switch = ft.Switch(label="Portrait (for portrait-oriented devices)", value=False)
    status = ft.Text("", color=ft.Colors.ON_SURFACE_VARIANT)

    picker = ft.FilePicker()
    page.services.append(picker)
    page.update()

    selected: dict[str, Any] = {"bytes": None, "name": None}
    upload_button = ft.FilledButton("Upload", icon=ft.Icons.UPLOAD, disabled=True)

    async def choose() -> None:
        files = await picker.pick_files(
            allow_multiple=False,
            allowed_extensions=["jpg", "jpeg", "png", "webp", "heic"],
            with_data=True,
        )
        if not files:
            return
        upload_file = files[0]
        if not upload_file.bytes:
            status.value = "File data not available"
            page.update()
            return
        selected["bytes"] = upload_file.bytes
        selected["name"] = upload_file.name
        status.value = f"Selected: {upload_file.name}"
        upload_button.disabled = False
        page.update()

    async def upload() -> None:
        if not selected["bytes"] or not selected["name"]:
            status.value = "Choose a file first"
            page.update()
            return
        try:
            duration = int(duration_field.value or 600)
        except ValueError:
            status.value = "Duration must be an integer"
            page.update()
            return
        metadata = {
            "source_name": "manual",
            "title": title_field.value or None,
            "description": description_field.value or None,
            "author": author_field.value or None,
            "tags": tags_field.value or None,
            "display_duration_seconds": duration,
            "priority": int(priority_slider.value or 5),
            "is_portrait": bool(portrait_switch.value),
        }
        status.value = "Uploading…"
        upload_button.disabled = True
        page.update()
        try:
            await api.upload_image(selected["bytes"], selected["name"], metadata)
        except ApiError as exc:
            status.value = f"Upload failed: {exc.detail or exc}"
            upload_button.disabled = False
            page.update()
            return
        status.value = "Uploaded"
        page.update()
        page.pop_dialog()
        await on_uploaded()

    upload_button.on_click = lambda _e: asyncio.create_task(upload())

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Upload image"),
        content=ft.Column(
            [
                title_field,
                description_field,
                author_field,
                tags_field,
                duration_field,
                priority_slider,
                portrait_switch,
                status,
            ],
            tight=True,
            width=420,
            scroll=ft.ScrollMode.AUTO,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=lambda _e: page.pop_dialog()),
            ft.OutlinedButton(
                "Choose file",
                icon=ft.Icons.ATTACH_FILE,
                on_click=lambda _e: asyncio.create_task(choose()),
            ),
            upload_button,
        ],
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
