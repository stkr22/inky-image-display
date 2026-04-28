"""Images view: gallery, upload, and full-route detail/edit."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import events, ui

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame

logger = logging.getLogger(__name__)

_PAGE_SIZE = 30
_SOURCE_OPTIONS: dict[str, str] = {"": "All", "manual": "manual", "immich": "immich"}


def register() -> None:
    """Register all image-related @ui.page routes with NiceGUI."""

    @ui.page("/images")
    async def gallery_page() -> None:
        with frame("/images"):
            await _render_gallery()

    @ui.page("/images/{image_id}")
    async def detail_page(image_id: str) -> None:
        with frame("/images"):
            await _render_detail(image_id)


async def _render_gallery() -> None:
    api = require_api_client()
    state: dict[str, Any] = {"offset": 0, "source_name": "", "is_portrait": False}

    page_label = ui.label()

    with ui.row().classes("w-full items-end gap-3 flex-wrap"):
        source_select = ui.select(_SOURCE_OPTIONS, value="", label="Source").classes("min-w-[160px]")
        portrait_switch = ui.switch("Portrait only", value=False)
        ui.space()
        prev_button = ui.button(icon="chevron_left").props("flat round")
        with ui.element("div").classes("flex items-center"):
            page_label.classes("text-sm")
        next_button = ui.button(icon="chevron_right").props("flat round")

    grid = (
        ui.element("div")
        .classes("grid w-full gap-3")
        .style("grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));")
    )

    async def reload() -> None:
        try:
            rows = await api.list_images(
                source_name=state["source_name"] or None,
                is_portrait=True if state["is_portrait"] else None,
                limit=_PAGE_SIZE,
                offset=state["offset"],
            )
        except ApiError as exc:
            logger.exception("list_images failed")
            ui.notify(f"Failed to load images: {exc.detail or exc}", type="negative")
            return
        grid.clear()
        with grid:
            if not rows:
                ui.label("No images.").classes("italic text-gray-500")
            for image in rows:
                _render_tile(image)
        offset = state["offset"]
        page_label.text = f"Showing {offset + 1}-{offset + len(rows)}" if rows else "No results"
        prev_button.set_enabled(offset > 0)
        next_button.set_enabled(len(rows) >= _PAGE_SIZE)

    async def on_source(e: events.ValueChangeEventArguments) -> None:
        state["source_name"] = e.value or ""
        state["offset"] = 0
        await reload()

    async def on_portrait(e: events.ValueChangeEventArguments) -> None:
        state["is_portrait"] = bool(e.value)
        state["offset"] = 0
        await reload()

    async def on_prev() -> None:
        state["offset"] = max(0, state["offset"] - _PAGE_SIZE)
        await reload()

    async def on_next() -> None:
        state["offset"] += _PAGE_SIZE
        await reload()

    source_select.on_value_change(on_source)
    portrait_switch.on_value_change(on_portrait)
    prev_button.on_click(on_prev)
    next_button.on_click(on_next)

    with ui.page_sticky(position="bottom-right", x_offset=18, y_offset=18):
        ui.button(icon="upload", on_click=lambda: _open_upload_dialog(reload)).props("fab color=primary").tooltip(
            "Upload image"
        )

    await reload()


def _render_tile(image: dict[str, Any]) -> None:
    storage_path = image["storage_path"]
    title = image.get("title") or storage_path.split("/")[-1]
    image_id = image["id"]
    with (
        ui.card()
        .tight()
        .classes("cursor-pointer overflow-hidden")
        .on("click", lambda iid=image_id: ui.navigate.to(f"/images/{iid}"))
    ):
        ui.image(f"/media/{storage_path}").classes("w-full aspect-square object-cover")
        ui.label(title).classes("text-xs px-2 py-1 truncate")


async def _render_detail(image_id: str) -> None:  # noqa: PLR0915
    api = require_api_client()
    try:
        image_uuid = UUID(image_id)
    except ValueError:
        ui.label("Invalid image id.").classes("text-red-500")
        return
    try:
        image = await api.get_image(image_uuid)
    except ApiError as exc:
        ui.notify(f"Load failed: {exc.detail or exc}", type="negative")
        ui.label("Could not load image.").classes("text-red-500")
        return

    with ui.row().classes("w-full gap-6 flex-wrap md:flex-nowrap items-start"):
        with ui.column().classes("flex-1 min-w-0 gap-2"):
            ui.image(f"/media/{image['storage_path']}").classes(
                "w-full max-h-[80vh] object-contain rounded shadow"
            ).props("loading=lazy")
            ui.label(image.get("title") or image["storage_path"].split("/")[-1]).classes("text-lg font-medium")

        with ui.column().classes("w-full md:w-[420px] gap-3"):
            title_field = ui.input("Title", value=image.get("title") or "").classes("w-full")
            description_field = (
                ui.textarea("Description", value=image.get("description") or "").classes("w-full").props("autogrow")
            )
            author_field = ui.input("Author", value=image.get("author") or "").classes("w-full")
            tags_field = ui.input("Tags (comma-separated)", value=image.get("tags") or "").classes("w-full")

            with ui.row().classes("w-full items-center gap-3"):
                duration_field = ui.number(
                    "Duration (s)",
                    value=int(image.get("display_duration_seconds") or 600),
                    min=1,
                    step=1,
                ).classes("w-32")
                with ui.column().classes("flex-1 gap-0"):
                    ui.label("Priority").classes("text-xs text-gray-500")
                    priority_slider = ui.slider(min=1, max=10, step=1, value=int(image.get("priority") or 5)).props(
                        "label-always"
                    )

            with ui.expansion("Metadata", icon="info").classes("w-full"):
                _render_metadata(image)

    async def save() -> None:
        try:
            duration = int(duration_field.value or 600)
        except (TypeError, ValueError):
            ui.notify("Duration must be an integer", type="negative")
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
            await api.update_image(image_uuid, body)
        except ApiError as exc:
            ui.notify(f"Update failed: {exc.detail or exc}", type="negative")
            return
        ui.notify("Saved", type="positive")
        ui.navigate.to("/images")

    async def delete() -> None:
        confirmed = await _confirm(f"Delete image '{image.get('title') or image['id']}'?")
        if not confirmed:
            return
        try:
            await api.delete_image(image_uuid)
        except ApiError as exc:
            ui.notify(f"Delete failed: {exc.detail or exc}", type="negative")
            return
        ui.notify("Deleted", type="positive")
        ui.navigate.to("/images")

    with (
        ui.page_sticky(position="bottom", x_offset=0, y_offset=0),
        ui.card().classes("w-full rounded-none border-t").tight(),
        ui.row().classes("w-full items-center justify-end p-3 gap-2 max-w-screen-xl mx-auto"),
    ):
        ui.button("Cancel", on_click=lambda: ui.navigate.to("/images")).props("flat")
        ui.button("Delete", icon="delete", on_click=delete).props("flat color=negative")
        ui.button("Save", icon="save", on_click=save).props("color=primary")


def _render_metadata(image: dict[str, Any]) -> None:
    dims = f"{image.get('original_width') or '?'}x{image.get('original_height') or '?'}"
    rows = [
        ("ID", image["id"]),
        ("Source", image.get("source_name") or "?"),
    ]
    if image.get("source_id"):
        rows.append(("Source ID", str(image["source_id"])))
    if image.get("sync_job_name"):
        rows.append(("Sync job", str(image["sync_job_name"])))
    rows.extend(
        [
            ("Dimensions", dims),
            ("Created", format_datetime(image.get("created_at"))),
            ("Last displayed", format_datetime(image.get("last_displayed_at"))),
        ]
    )

    with ui.column().classes("w-full gap-1 py-2"):
        for label, value in rows:
            with ui.row().classes("w-full items-baseline gap-2"):
                ui.label(label).classes("text-xs text-gray-500 w-28 shrink-0")
                ui.label(str(value)).classes("text-xs break-all").style("user-select: text;")
        source_url = image.get("source_url")
        if source_url and source_url.startswith(("http://", "https://")):
            with ui.row().classes("w-full items-baseline gap-2"):
                ui.label("Source URL").classes("text-xs text-gray-500 w-28 shrink-0")
                ui.link(source_url, target=source_url, new_tab=True).classes("text-xs break-all")
        elif source_url:
            with ui.row().classes("w-full items-baseline gap-2"):
                ui.label("Source URL").classes("text-xs text-gray-500 w-28 shrink-0")
                ui.label(str(source_url)).classes("text-xs break-all")


def _open_upload_dialog(on_uploaded: Any) -> None:
    api = require_api_client()
    selected: dict[str, Any] = {"bytes": None, "name": None}

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
        ui.label("Upload image").classes("text-lg font-medium")

        title_field = ui.input("Title").classes("w-full")
        description_field = ui.textarea("Description").classes("w-full").props("autogrow")
        author_field = ui.input("Author").classes("w-full")
        tags_field = ui.input("Tags (comma-separated)").classes("w-full")

        with ui.row().classes("w-full items-center gap-3"):
            duration_field = ui.number("Duration (s)", value=600, min=1, step=1).classes("w-32")
            with ui.column().classes("flex-1 gap-0"):
                ui.label("Priority").classes("text-xs text-gray-500")
                priority_slider = ui.slider(min=1, max=10, step=1, value=5).props("label-always")

        portrait_switch = ui.switch("Portrait (for portrait-oriented devices)", value=False)

        async def on_upload(e: events.UploadEventArguments) -> None:
            selected["bytes"] = await e.file.read()
            selected["name"] = e.file.name
            ui.notify(f"Selected: {e.file.name}")

        upload = (
            ui.upload(
                label="Choose file",
                auto_upload=True,
                max_files=1,
                on_upload=on_upload,
            )
            .props('accept=".jpg,.jpeg,.png,.webp,.heic"')
            .classes("w-full")
        )
        upload.on("rejected", lambda _e: ui.notify("File rejected", type="warning"))

        async def submit() -> None:
            if not selected["bytes"] or not selected["name"]:
                ui.notify("Choose a file first", type="warning")
                return
            try:
                duration = int(duration_field.value or 600)
            except (TypeError, ValueError):
                ui.notify("Duration must be an integer", type="negative")
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
            try:
                await api.upload_image(selected["bytes"], selected["name"], metadata)
            except ApiError as exc:
                ui.notify(f"Upload failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Uploaded", type="positive")
            dialog.close()
            await on_uploaded()

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Upload", icon="upload", on_click=submit).props("color=primary")

    dialog.open()


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("color=primary")
    result = await dialog
    return bool(result)
