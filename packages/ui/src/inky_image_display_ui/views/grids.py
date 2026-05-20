"""Grids view: list/create/edit grids and manage device placements."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import ui

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import (
    format_datetime,
    format_interval_seconds,
    format_relative,
    split_hours_minutes,
)
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._quality import (
    CROP_NEGLIGIBLE,
    image_fit,
    max_device_pxcm,
    resolution_band,
)

logger = logging.getLogger(__name__)


def register() -> None:
    """Register the grids routes."""

    @ui.page("/grids/{grid_id}")
    async def grid_detail_page(grid_id: str) -> None:
        with frame("/displays"):
            await _render_detail(UUID(grid_id))


async def render_section() -> None:
    """Render the Grids list section inside the unified Display page."""
    api = require_api_client()

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Wall").classes("ink-eyebrow")
            ui.label("Grids").classes("ink-h2")
        with ui.row().classes("gap-2"):
            create_btn = ui.button(icon="add", on_click=lambda: _open_create_dialog(api, reload)).props(
                "unelevated color=primary"
            )
            create_btn.tooltip("Create grid")
            refresh_btn = ui.button(icon="refresh").props("flat round").tooltip("Refresh")

    container = ui.column().classes("w-full gap-3")

    async def reload() -> None:
        try:
            grids = await api.list_grids(include_devices=True)
        except ApiError as exc:
            ui.notify(f"Failed to load grids: {exc.detail or exc}", type="negative")
            return
        container.clear()
        with container:
            if not grids:
                ui.label("No grids yet — create one to start.").classes("italic text-gray-500")
                return
            for grid in grids:
                _render_grid_card(grid)

    refresh_btn.on_click(reload)
    await reload()


def _render_grid_card(grid: dict[str, Any]) -> None:
    devices = grid.get("devices") or []
    with (
        ui.link(target=f"/grids/{grid['id']}")
        .classes("w-full no-underline")
        .style(
            "color: inherit; padding: 20px; background: var(--ink-surface);"
            " border: 1px solid var(--ink-border); border-radius: 20px;"
            " box-shadow: 0 1px 2px rgba(11,18,32,0.04); display: flex; gap: 10px;"
            " align-items: center; justify-content: space-between; transition: border-color 120ms;"
        ),
        ui.row().classes("w-full items-center justify-between"),
    ):
        with ui.column().classes("gap-0"):
            ui.label(grid["name"]).classes("ink-h3")
            ui.label(f"{grid['width_cm']:.1f} x {grid['height_cm']:.1f} cm").classes("ink-small")
        ui.label(f"{len(devices)} device(s)").classes("ink-small")


async def _render_detail(grid_id: UUID) -> None:
    api = require_api_client()
    container = ui.column().classes("w-full gap-3")
    state: dict[str, Any] = {"preview_image_id": None}

    async def reload() -> None:
        try:
            grid = await api.get_grid(grid_id)
            devices = await api.list_devices()
            images = await api.list_images(limit=200)
            profiles = await api.list_device_profiles()
        except ApiError as exc:
            ui.notify(f"Failed to load grid: {exc.detail or exc}", type="negative")
            return

        image_by_id = {img["id"]: img for img in images}
        preview_image = _pick_preview_image(grid, image_by_id, state["preview_image_id"])
        max_pxcm = max_device_pxcm(grid, devices, profiles)

        container.clear()
        with container:
            _render_grid_header(api, grid, reload)
            _render_canvas_preview(grid, devices, preview_image, max_pxcm)
            _render_placements(api, grid, devices, profiles, reload)
            _render_image_actions(api, grid, images, state, max_pxcm, reload)

    await reload()


def _pick_preview_image(
    grid: dict[str, Any],
    image_by_id: dict[str, dict[str, Any]],
    preview_id: str | None,
) -> dict[str, Any] | None:
    if preview_id and preview_id in image_by_id:
        return image_by_id[preview_id]
    current = grid.get("current_image_id")
    if current and current in image_by_id:
        return image_by_id[current]
    return None


def _render_canvas_preview(
    grid: dict[str, Any],
    all_devices: list[dict[str, Any]],
    preview_image: dict[str, Any] | None,
    max_pxcm: float | None,
) -> None:
    """Proportional canvas with device rectangles overlaid on the source image.

    The background uses CSS ``background-size: cover`` + ``center`` which
    matches the API's cover-fit crop math exactly — so each overlaid
    rectangle frames the same source-image region that device actually
    receives.
    """
    placements = grid.get("devices") or []
    device_by_id = {d["id"]: d for d in all_devices}
    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])

    bg_style = (
        f"background-image: url('/media/{preview_image['storage_path']}');"
        " background-size: cover; background-position: center;"
        if preview_image
        else "background: repeating-linear-gradient(45deg, #f4f5f7, #f4f5f7 12px, #ebedf0 12px, #ebedf0 24px);"
    )

    with ui.element("div").style(
        "width: 100%; padding: 16px; background: var(--ink-surface);"
        " border: 1px solid var(--ink-border); border-radius: 16px; display: flex;"
        " flex-direction: column; gap: 10px;"
    ):
        with ui.row().classes("w-full items-baseline justify-between"):
            ui.label("Layout preview").classes("ink-h3")
            if preview_image:
                title = preview_image.get("title") or preview_image["storage_path"].split("/")[-1]
                ui.label(f"Preview: {title}").classes("ink-small")
            else:
                ui.label("No image selected — use Preview below to pick one.").classes("ink-small")

        with ui.row().classes("w-full gap-4 flex-wrap items-start"):
            canvas = ui.element("div").style(
                f"flex: 1 1 480px; max-width: 720px; aspect-ratio: {grid_w} / {grid_h};"
                " position: relative; border: 1px solid var(--ink-border);"
                f" border-radius: 8px; overflow: hidden; {bg_style}"
            )
            with canvas:
                for placement in placements:
                    device = device_by_id.get(placement["device_id"])
                    label = device["device_id"] if device else placement["device_id"][:8]
                    # API gives bottom-left (Y-up); CSS wants top-left (Y-down).
                    left_pct = placement["bottom_left_x_cm"] / grid_w * 100
                    top_pct = (grid_h - placement["bottom_left_y_cm"] - placement["height_cm"]) / grid_h * 100
                    width_pct = placement["width_cm"] / grid_w * 100
                    height_pct = placement["height_cm"] / grid_h * 100
                    with ui.element("div").style(
                        f"position: absolute; left: {left_pct:.4f}%; top: {top_pct:.4f}%;"
                        f" width: {width_pct:.4f}%; height: {height_pct:.4f}%;"
                        " border: 2px solid rgba(11, 18, 32, 0.75);"
                        " box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.7) inset;"
                        " display: flex; align-items: flex-end; justify-content: flex-start;"
                        " padding: 4px 6px;"
                    ):
                        ui.label(label).style(
                            "background: rgba(11, 18, 32, 0.78); color: #fff;"
                            " font-size: 11px; padding: 2px 6px; border-radius: 4px;"
                            " white-space: nowrap;"
                        )

            if preview_image:
                _render_source_with_used_region(preview_image, grid)

        _render_recommendation_line(grid, max_pxcm, preview_image)


def _render_source_with_used_region(image: dict[str, Any], grid: dict[str, Any]) -> None:
    """Thumbnail of the full source image with the kept region outlined.

    The dimmed strips show exactly what the cover-fit crops away.
    """
    img_w = image.get("original_width")
    img_h = image.get("original_height")
    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])

    with ui.column().classes("gap-1").style("flex: 0 0 240px; min-width: 200px;"):
        ui.label("Source image").classes("ink-eyebrow")
        if not img_w or not img_h:
            ui.label("(dimensions unknown)").classes("ink-small")
            return
        canvas_aspect = grid_w / grid_h
        image_aspect = img_w / img_h
        if image_aspect > canvas_aspect:
            used_w_pct = canvas_aspect / image_aspect * 100
            used_left_pct = (100 - used_w_pct) / 2
            used_top_pct, used_h_pct = 0.0, 100.0
        else:
            used_h_pct = image_aspect / canvas_aspect * 100
            used_top_pct = (100 - used_h_pct) / 2
            used_left_pct, used_w_pct = 0.0, 100.0

        with ui.element("div").style(
            f"position: relative; width: 100%; aspect-ratio: {img_w} / {img_h};"
            " border: 1px solid var(--ink-border); border-radius: 6px; overflow: hidden;"
            f" background-image: url('/media/{image['storage_path']}');"
            " background-size: cover; background-position: center;"
        ):
            # Dim the cropped strips (everything except the kept region).
            for left, top, width, height in _cropped_strips(used_left_pct, used_top_pct, used_w_pct, used_h_pct):
                ui.element("div").style(
                    f"position: absolute; left: {left:.4f}%; top: {top:.4f}%;"
                    f" width: {width:.4f}%; height: {height:.4f}%;"
                    " background: rgba(11, 18, 32, 0.55);"
                )
            # Outline the kept region.
            ui.element("div").style(
                f"position: absolute; left: {used_left_pct:.4f}%; top: {used_top_pct:.4f}%;"
                f" width: {used_w_pct:.4f}%; height: {used_h_pct:.4f}%;"
                " border: 2px solid rgba(255, 255, 255, 0.95);"
                " box-shadow: 0 0 0 1px rgba(11, 18, 32, 0.4);"
            )

        cropped_pct = 100 - used_w_pct * used_h_pct / 100
        if cropped_pct < CROP_NEGLIGIBLE * 100:
            ui.label("Aspect matches the canvas — nothing cropped.").classes("ink-small")
        else:
            axis = "horizontal" if image_aspect > canvas_aspect else "vertical"
            ui.label(f"{cropped_pct:.0f}% cropped ({axis})").classes("ink-small")


def _cropped_strips(left: float, top: float, width: float, height: float) -> list[tuple[float, float, float, float]]:
    """Return the rectangles outside the kept region (for dimming overlay)."""
    strips: list[tuple[float, float, float, float]] = []
    if left > 0:
        strips.append((0.0, 0.0, left, 100.0))
    right_gap = 100 - (left + width)
    if right_gap > 0:
        strips.append((left + width, 0.0, right_gap, 100.0))
    if top > 0:
        strips.append((left, 0.0, width, top))
    bottom_gap = 100 - (top + height)
    if bottom_gap > 0:
        strips.append((left, top + height, width, bottom_gap))
    return strips


def _render_recommendation_line(
    grid: dict[str, Any],
    max_pxcm: float | None,
    preview_image: dict[str, Any] | None,
) -> None:
    """Recommended minimum source-image dimensions and current-image verdict."""
    if max_pxcm is None:
        ui.label("Place a device to see recommended image dimensions.").classes("ink-small")
        return

    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])
    rec_w = int(grid_w * max_pxcm + 0.999)
    rec_h = int(grid_h * max_pxcm + 0.999)

    parts = [f"Recommended ≥ {rec_w}x{rec_h} px (densest device: {max_pxcm:.0f} px/cm)."]
    if preview_image:
        fit = image_fit(preview_image.get("original_width") or 0, preview_image.get("original_height") or 0, grid)
        if fit is not None:
            ratio = fit["effective_pxcm"] / max_pxcm if max_pxcm > 0 else 0.0
            band, colour = resolution_band(ratio)
            img_w = preview_image.get("original_width")
            img_h = preview_image.get("original_height")
            parts.append(
                f"Current: {img_w}x{img_h} px → {fit['effective_pxcm']:.0f} px/cm effective "
                f"({ratio:.2f}x target, {band})."
            )
            ui.label(" ".join(parts)).classes("ink-small").style(f"color: {colour};")
            return
    ui.label(" ".join(parts)).classes("ink-small")


def _render_grid_header(api: Any, grid: dict[str, Any], on_changed: Any) -> None:
    async def do_delete() -> None:
        if not await _confirm(f"Delete grid '{grid['name']}'? Member devices return to solo rotation."):
            return
        try:
            await api.delete_grid(UUID(grid["id"]))
        except ApiError as exc:
            ui.notify(f"Delete failed: {exc.detail or exc}", type="negative")
            return
        ui.notify("Grid deleted", type="positive")
        ui.navigate.to("/displays")

    with ui.row().classes("w-full items-end justify-between flex-wrap gap-3"):
        with ui.column().classes("gap-0"):
            ui.label("Grid").classes("ink-eyebrow")
            ui.label(grid["name"]).classes("ink-h2")
            ui.label(f"Canvas: {grid['width_cm']:.1f} x {grid['height_cm']:.1f} cm").classes("ink-small")
            next_at = grid.get("scheduled_next_at")
            interval_label = format_interval_seconds(grid.get("refresh_interval_seconds"), default_label="default")
            ui.label(
                f"Refresh every {interval_label} · next {format_datetime(next_at)} ({format_relative(next_at)})"
            ).classes("ink-small")
        with ui.row().classes("gap-2 items-center"):
            ui.link("← Displays", "/displays").classes("ink-small")
            ui.button(
                "Edit",
                icon="edit",
                on_click=lambda: _open_edit_dialog(api, grid, on_changed),
            ).props("flat")
            ui.button("Delete", icon="delete", on_click=do_delete).props("flat color=negative")


async def _open_edit_dialog(api: Any, grid: dict[str, Any], on_done: Any) -> None:
    current_interval = grid.get("refresh_interval_seconds")
    int_hours, int_minutes = split_hours_minutes(current_interval)
    default_label = await _fetch_default_label(api)
    with ui.dialog() as dialog, ui.card().style("padding: 20px; min-width: 360px; gap: 12px;"):
        ui.label("Edit grid").classes("ink-h3")
        name = ui.input("Name", value=grid["name"]).props("outlined")
        width = ui.number("Width (cm)", value=float(grid["width_cm"]), step=1, min=1).props("outlined")
        height = ui.number("Height (cm)", value=float(grid["height_cm"]), step=1, min=1).props("outlined")
        ui.label(
            "Resizing re-validates every placed device — devices whose rectangle would fall off"
            " the new canvas reject the change."
        ).classes("ink-small")

        ui.label("Refresh schedule").classes("ink-eyebrow")
        use_default = ui.switch(f"Use default interval ({default_label})", value=current_interval is None)
        hours_input = ui.number("Hours", value=int_hours, min=0, step=1).props("outlined")
        minutes_input = ui.number("Minutes", value=int_minutes, min=0, max=59, step=1).props("outlined")

        def sync_enabled() -> None:
            enabled = not use_default.value
            hours_input.set_enabled(enabled)
            minutes_input.set_enabled(enabled)

        use_default.on_value_change(lambda _e: sync_enabled())
        sync_enabled()

        async def submit() -> None:
            payload: dict[str, Any] = {}
            if name.value and name.value != grid["name"]:
                payload["name"] = name.value
            if width.value and float(width.value) != float(grid["width_cm"]):
                payload["width_cm"] = float(width.value)
            if height.value and float(height.value) != float(grid["height_cm"]):
                payload["height_cm"] = float(height.value)

            if use_default.value:
                if current_interval is not None:
                    payload["clear_refresh_interval"] = True
            else:
                total_seconds = int(hours_input.value or 0) * 3600 + int(minutes_input.value or 0) * 60
                if total_seconds <= 0:
                    ui.notify("Pick at least 1 minute, or switch to default.", type="warning")
                    return
                if total_seconds != (current_interval or -1):
                    payload["refresh_interval_seconds"] = total_seconds
            if not payload:
                dialog.close()
                return
            try:
                await api.update_grid(UUID(grid["id"]), payload)
            except ApiError as exc:
                ui.notify(f"Update failed: {exc.detail or exc}", type="negative")
                return
            dialog.close()
            ui.notify("Grid updated", type="positive")
            await on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Save", on_click=submit).props("unelevated color=primary")
    dialog.open()


async def _fetch_default_label(api: Any) -> str:
    """Return the global default refresh interval as a short human string."""
    try:
        settings = await api.get_app_settings()
    except ApiError:
        return "default"
    return format_interval_seconds(int(settings.get("default_refresh_seconds") or 0))


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card().style("padding: 20px; gap: 12px; min-width: 320px;"):
        ui.label(message).classes("ink-body")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("unelevated color=primary")
    result = await dialog
    return bool(result)


def _render_placements(
    api: Any,
    grid: dict[str, Any],
    all_devices: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    on_changed: Any,
) -> None:
    profile_by_id = {p["id"]: p for p in profiles}
    with ui.element("div").style(
        "width: 100%; padding: 16px; background: var(--ink-surface);"
        " border: 1px solid var(--ink-border); border-radius: 16px; display: flex;"
        " flex-direction: column; gap: 12px;"
    ):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Devices").classes("ink-h3")
            placed_ids = {d["device_id"] for d in (grid.get("devices") or [])}
            unplaced = [d for d in all_devices if d["id"] not in placed_ids]
            add_btn = ui.button(
                "Add device",
                icon="add",
                on_click=lambda: _open_add_device_dialog(api, grid, unplaced, profile_by_id, on_changed),
            ).props("unelevated color=primary")
            add_btn.set_enabled(bool(unplaced))

        placements = grid.get("devices") or []
        if not placements:
            ui.label("No devices placed yet.").classes("italic text-gray-500")
            return

        device_by_id = {d["id"]: d for d in all_devices}
        for placement in placements:
            _render_placement_row(api, grid, placement, device_by_id, on_changed)


def _render_placement_row(
    api: Any,
    grid: dict[str, Any],
    placement: dict[str, Any],
    device_by_id: dict[str, dict[str, Any]],
    on_changed: Any,
) -> None:
    device = device_by_id.get(placement["device_id"])
    device_label = device["device_id"] if device else placement["device_id"][:8]

    async def do_remove() -> None:
        try:
            await api.remove_device_from_grid(UUID(grid["id"]), UUID(placement["device_id"]))
        except ApiError as exc:
            ui.notify(f"Remove failed: {exc.detail or exc}", type="negative")
            return
        ui.notify("Device removed", type="positive")
        await on_changed()

    with (
        ui.row()
        .classes("w-full items-center justify-between")
        .style("border-top: 1px solid var(--ink-border); padding-top: 10px;")
    ):
        with ui.column().classes("gap-0"):
            ui.label(device_label).classes("ink-body")
            ui.label(
                f"bottom-left ({placement['bottom_left_x_cm']:.1f}, {placement['bottom_left_y_cm']:.1f}) cm · "
                f"{placement['width_cm']:.1f} x {placement['height_cm']:.1f} cm"
            ).classes("ink-small")
        with ui.row().classes("gap-2"):
            ui.button(
                "Move",
                icon="open_with",
                on_click=lambda: _open_move_dialog(api, grid, placement, on_changed),
            ).props("flat")
            ui.button("Remove", icon="delete", on_click=do_remove).props("flat color=negative")


def _render_image_actions(  # noqa: PLR0913 — passes through caller-side state
    api: Any,
    grid: dict[str, Any],
    all_images: list[dict[str, Any]],
    state: dict[str, Any],
    max_pxcm: float | None,
    on_changed: Any,
) -> None:
    grid_images = [img for img in all_images if img.get("target_grid_id") == grid["id"]]

    with ui.element("div").style(
        "width: 100%; padding: 16px; background: var(--ink-surface);"
        " border: 1px solid var(--ink-border); border-radius: 16px; display: flex;"
        " flex-direction: column; gap: 12px;"
    ):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Images for this grid").classes("ink-h3")

            async def do_release() -> None:
                try:
                    await api.release_grid(UUID(grid["id"]))
                except ApiError as exc:
                    ui.notify(f"Release failed: {exc.detail or exc}", type="negative")
                    return
                ui.notify("Grid released — devices return to solo.", type="positive")
                await on_changed()

            ui.button("Release devices", icon="logout", on_click=do_release).props("flat")

        if not grid_images:
            ui.label("No images target this grid. Upload an image and pick this grid as target.").classes(
                "italic text-gray-500"
            )
            return

        grid_el = (
            ui.element("div")
            .classes("grid w-full gap-3")
            .style("grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));")
        )
        with grid_el:
            for image in grid_images:
                _render_grid_image_tile(api, grid, image, state, max_pxcm, on_changed)


def _render_grid_image_tile(  # noqa: PLR0913 — passes through caller-side state
    api: Any,
    grid: dict[str, Any],
    image: dict[str, Any],
    state: dict[str, Any],
    max_pxcm: float | None,
    on_changed: Any,
) -> None:
    async def do_display() -> None:
        try:
            await api.display_grid_image(UUID(grid["id"]), UUID(image["id"]))
        except ApiError as exc:
            ui.notify(f"Display failed: {exc.detail or exc}", type="negative")
            return
        ui.notify(f"Showing on {grid['name']}", type="positive")
        await on_changed()

    async def do_preview() -> None:
        state["preview_image_id"] = image["id"]
        await on_changed()

    is_previewed = state.get("preview_image_id") == image["id"]
    border_color = "var(--ink-primary, #4f46e5)" if is_previewed else "var(--ink-border)"

    with ui.element("div").style(
        f"border: 2px solid {border_color}; border-radius: 12px;"
        " overflow: hidden; display: flex; flex-direction: column;"
    ):
        ui.image(f"/media/{image['storage_path']}").props("loading=lazy").style(
            "width: 100%; aspect-ratio: 4/3; object-fit: cover;"
        )
        with ui.column().classes("gap-1 p-3"):
            ui.label(image.get("title") or image["storage_path"]).classes("ink-body").style(
                "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
            )
            _render_image_hints(image, grid, max_pxcm)
            with ui.row().classes("w-full gap-2 flex-wrap"):
                ui.button("Preview", icon="visibility", on_click=do_preview).props("flat")
                ui.button("Display now", icon="play_arrow", on_click=do_display).props("unelevated color=primary")


def _render_image_hints(
    image: dict[str, Any],
    grid: dict[str, Any],
    max_pxcm: float | None,
) -> None:
    """Aspect-drift + resolution badge per image tile."""
    fit = image_fit(image.get("original_width") or 0, image.get("original_height") or 0, grid)
    if fit is None:
        ui.label("Resolution unknown").classes("ink-small")
        return

    crop_text = (
        "no crop" if fit["crop_pct"] < CROP_NEGLIGIBLE else f"{fit['crop_pct'] * 100:.0f}% {fit['crop_axis']} crop"
    )
    aspect_line = f"{fit['image_aspect']:.2f}:1 vs grid {fit['canvas_aspect']:.2f}:1 — {crop_text}"

    badge_text, badge_colour = "", ""
    if max_pxcm:
        ratio = fit["effective_pxcm"] / max_pxcm if max_pxcm > 0 else 0.0
        band, badge_colour = resolution_band(ratio)
        glyph = {"sharp": "✓", "soft": "⚠", "upscaled": "✗"}[band]
        badge_text = f"{glyph} {band} ({ratio:.2f}x)"

    with ui.row().classes("w-full gap-2 items-center"):
        ui.label(aspect_line).classes("ink-small").style(
            "white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1 1 auto;"
        )
        if badge_text:
            ui.label(badge_text).style(
                f"font-size: 11px; padding: 2px 6px; border-radius: 4px;"
                f" background: rgba(11,18,32,0.06); color: {badge_colour};"
                " white-space: nowrap;"
            )


async def _open_create_dialog(api: Any, on_done: Any) -> None:
    with ui.dialog() as dialog, ui.card().style("padding: 20px; min-width: 360px; gap: 12px;"):
        ui.label("New grid").classes("ink-h3")
        name = ui.input("Name").props("outlined")
        width = ui.number("Width (cm)", value=80.0, step=1).props("outlined")
        height = ui.number("Height (cm)", value=40.0, step=1).props("outlined")

        async def submit() -> None:
            try:
                await api.create_grid({"name": name.value, "width_cm": width.value, "height_cm": height.value})
            except ApiError as exc:
                ui.notify(f"Create failed: {exc.detail or exc}", type="negative")
                return
            dialog.close()
            ui.notify("Grid created", type="positive")
            await on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Create", on_click=submit).props("unelevated color=primary")
    dialog.open()


def _device_dims_cm(device: dict[str, Any], profile_by_id: dict[str, dict[str, Any]]) -> tuple[float, float]:
    """Return (width_cm, height_cm) for a device as mounted (portrait swaps axes)."""
    profile = profile_by_id.get(device["device_profile_id"])
    if profile is None:
        return 0.0, 0.0
    if device["display_orientation"] == "portrait":
        return float(profile["physical_height_cm"]), float(profile["physical_width_cm"])
    return float(profile["physical_width_cm"]), float(profile["physical_height_cm"])


async def _open_add_device_dialog(
    api: Any,
    grid: dict[str, Any],
    unplaced: list[dict[str, Any]],
    profile_by_id: dict[str, dict[str, Any]],
    on_done: Any,
) -> None:
    if not unplaced:
        ui.notify("All devices are already placed on this grid.", type="warning")
        return

    options = {d["id"]: d["device_id"] for d in unplaced}
    device_by_id = {d["id"]: d for d in unplaced}
    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])

    with ui.dialog() as dialog, ui.card().style("padding: 20px; min-width: 380px; gap: 12px;"):
        ui.label("Place device").classes("ink-h3")
        ui.label(f"Origin (0, 0) is the grid's bottom-left corner. Canvas: {grid_w:.1f} x {grid_h:.1f} cm.").classes(
            "ink-small"
        )
        device_select = ui.select(options=options, label="Device").props("outlined")
        width_pos = ui.number("Width position (cm)", value=0.0, step=0.5).props("outlined")
        width_hint = ui.label("Pick a device to see allowed range.").classes("ink-small")
        height_pos = ui.number("Height position (cm)", value=0.0, step=0.5).props("outlined")
        height_hint = ui.label("Pick a device to see allowed range.").classes("ink-small")

        def update_hints() -> None:
            sel = device_select.value
            if not sel:
                width_hint.text = "Pick a device to see allowed range."
                height_hint.text = "Pick a device to see allowed range."
                return
            dev = device_by_id.get(str(sel))
            if dev is None:
                return
            dev_w, dev_h = _device_dims_cm(dev, profile_by_id)
            width_hint.text = f"Allowed: 0 to {max(0.0, grid_w - dev_w):.1f} cm (device width {dev_w:.1f} cm)"
            height_hint.text = f"Allowed: 0 to {max(0.0, grid_h - dev_h):.1f} cm (device height {dev_h:.1f} cm)"

        device_select.on_value_change(lambda _e: update_hints())

        async def submit() -> None:
            if not device_select.value:
                ui.notify("Pick a device", type="warning")
                return
            try:
                await api.add_device_to_grid(
                    UUID(grid["id"]),
                    {
                        "device_id": str(device_select.value),
                        "bottom_left_x_cm": width_pos.value,
                        "bottom_left_y_cm": height_pos.value,
                    },
                )
            except ApiError as exc:
                ui.notify(f"Add failed: {exc.detail or exc}", type="negative")
                return
            dialog.close()
            ui.notify("Device placed", type="positive")
            await on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Place", on_click=submit).props("unelevated color=primary")
    dialog.open()


async def _open_move_dialog(
    api: Any,
    grid: dict[str, Any],
    placement: dict[str, Any],
    on_done: Any,
) -> None:
    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])
    dev_w = float(placement["width_cm"])
    dev_h = float(placement["height_cm"])

    with ui.dialog() as dialog, ui.card().style("padding: 20px; min-width: 380px; gap: 12px;"):
        ui.label("Move device").classes("ink-h3")
        ui.label(f"Origin (0, 0) is the grid's bottom-left corner. Canvas: {grid_w:.1f} x {grid_h:.1f} cm.").classes(
            "ink-small"
        )
        width_pos = ui.number("Width position (cm)", value=placement["bottom_left_x_cm"], step=0.5).props("outlined")
        ui.label(f"Allowed: 0 to {max(0.0, grid_w - dev_w):.1f} cm (device width {dev_w:.1f} cm)").classes("ink-small")
        height_pos = ui.number("Height position (cm)", value=placement["bottom_left_y_cm"], step=0.5).props("outlined")
        ui.label(f"Allowed: 0 to {max(0.0, grid_h - dev_h):.1f} cm (device height {dev_h:.1f} cm)").classes("ink-small")

        async def submit() -> None:
            try:
                await api.update_device_placement(
                    UUID(grid["id"]),
                    UUID(placement["device_id"]),
                    {"bottom_left_x_cm": width_pos.value, "bottom_left_y_cm": height_pos.value},
                )
            except ApiError as exc:
                ui.notify(f"Move failed: {exc.detail or exc}", type="negative")
                return
            dialog.close()
            ui.notify("Device moved", type="positive")
            await on_done()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Save", on_click=submit).props("unelevated color=primary")
    dialog.open()
