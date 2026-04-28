"""Sync jobs view: list with active toggle + create/edit form."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from nicegui import events, ui

from inky_image_display_ui.api_client import ApiClient, ApiError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame

logger = logging.getLogger(__name__)

_STRATEGIES = ["RANDOM", "SMART"]
_MIN_COUNT = 1
_MAX_COUNT = 1000
_FAVORITE_OPTIONS: dict[str, str] = {"": "Any", "true": "Favorites only", "false": "Non-favorites only"}
_RATING_OPTIONS: dict[str, str] = {"": "Any", **{str(i): f">= {i}" for i in range(6)}}


def register() -> None:
    """Register sync-job page routes."""

    @ui.page("/sync-jobs")
    async def list_page() -> None:
        with frame("/sync-jobs"):
            await _render_list()

    @ui.page("/sync-jobs/new")
    async def create_page() -> None:
        with frame("/sync-jobs"):
            await _render_form(job_id=None)

    @ui.page("/sync-jobs/{job_id}")
    async def edit_page(job_id: str) -> None:
        with frame("/sync-jobs"):
            await _render_form(job_id=job_id)


async def _render_list() -> None:
    api = require_api_client()
    device_map = await _load_device_map(api)

    with ui.row().classes("w-full items-center"):
        ui.label("Sync jobs").classes("text-2xl font-medium")
        ui.space()
        refresh_button = ui.button(icon="refresh").props("flat round").tooltip("Refresh")
        ui.button("New job", icon="add", on_click=lambda: ui.navigate.to("/sync-jobs/new")).props("color=primary")

    container = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        try:
            jobs = await api.list_sync_jobs()
        except ApiError as exc:
            ui.notify(f"Failed to load sync jobs: {exc.detail or exc}", type="negative")
            return
        container.clear()
        with container:
            if not jobs:
                ui.label("No sync jobs yet.").classes("italic text-gray-500")
                return
            for job in jobs:
                _render_row(api, job, device_map, reload)

    refresh_button.on_click(reload)
    await reload()


def _render_row(api: ApiClient, job: dict[str, Any], device_map: dict[str, str], on_changed: Any) -> None:
    job_id = UUID(job["id"])
    target_name = device_map.get(job["target_device_id"], job["target_device_id"])

    async def toggle_active(e: events.ValueChangeEventArguments) -> None:
        new_value = bool(e.value)
        try:
            await api.update_sync_job(job_id, {"is_active": new_value})
        except ApiError as exc:
            ui.notify(f"Toggle failed: {exc.detail or exc}", type="negative")
            switch.value = not new_value
            return
        ui.notify("Updated", type="positive")

    async def delete() -> None:
        if not await _confirm(f"Delete sync job '{job['name']}'?"):
            return
        try:
            await api.delete_sync_job(job_id)
        except ApiError as exc:
            ui.notify(f"Delete failed: {exc.detail or exc}", type="negative")
            return
        ui.notify("Deleted", type="positive")
        await on_changed()

    with ui.card().classes("w-full"), ui.row().classes("w-full items-center gap-3"):
        with ui.column().classes("flex-1 gap-0 min-w-0"):
            ui.label(job["name"]).classes("text-base font-medium truncate")
            ui.label(f"{job['strategy']} · count={job['count']} · → {target_name}").classes("text-xs text-gray-500")
            ui.label(f"Updated: {format_datetime(job.get('updated_at'))}").classes("text-xs text-gray-500")
        switch = ui.switch(value=bool(job.get("is_active"))).tooltip("Active")
        switch.on_value_change(toggle_active)
        ui.button(icon="edit", on_click=lambda jid=job["id"]: ui.navigate.to(f"/sync-jobs/{jid}")).props(
            "flat round"
        ).tooltip("Edit")
        ui.button(icon="delete", on_click=delete).props("flat round color=negative").tooltip("Delete")


async def _render_form(*, job_id: str | None) -> None:  # noqa: PLR0915
    api = require_api_client()
    devices = await _load_devices(api)
    device_options: dict[str, str] = {d["id"]: d.get("device_id") or d["id"] for d in devices}

    job: dict[str, Any] = {}
    if job_id is not None:
        try:
            job = await api.get_sync_job(UUID(job_id))
        except ApiError as exc:
            ui.notify(f"Load failed: {exc.detail or exc}", type="negative")
            ui.label("Could not load sync job.").classes("text-red-500")
            return

    title = "New sync job" if job_id is None else "Edit sync job"
    with ui.row().classes("w-full items-center"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/sync-jobs")).props("flat round")
        ui.label(title).classes("text-2xl font-medium")

    with ui.expansion("Basics", icon="settings", value=True).classes("w-full"):
        name_field = ui.input("Name", value=job.get("name") or "").classes("w-full")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            strategy_field = ui.select(_STRATEGIES, value=job.get("strategy") or "RANDOM", label="Strategy").classes(
                "min-w-[160px]"
            )
            query_field = ui.input("Query (SMART only)", value=job.get("query") or "").classes("flex-1 min-w-[200px]")
        target_field = ui.select(
            device_options,
            value=job.get("target_device_id") or (devices[0]["id"] if devices else None),
            label="Target device",
        ).classes("w-full")
        with ui.row().classes("w-full gap-3 items-center flex-wrap"):
            count_field = ui.number(
                "Count (1-1000)", value=int(job.get("count") or 10), min=_MIN_COUNT, max=_MAX_COUNT, step=1
            ).classes("w-40")
            random_pick = ui.switch("Random pick", value=bool(job.get("random_pick")))
        with ui.column().classes("w-full gap-0"):
            ui.label("Overfetch multiplier").classes("text-xs text-gray-500")
            overfetch_slider = ui.slider(min=1, max=10, step=1, value=int(job.get("overfetch_multiplier") or 3)).props(
                "label-always"
            )
        active_switch = ui.switch("Active", value=bool(job.get("is_active", True)))

    def _refresh_query_enabled() -> None:
        query_field.set_enabled(strategy_field.value == "SMART")

    strategy_field.on_value_change(lambda _e: _refresh_query_enabled())
    _refresh_query_enabled()

    with ui.expansion("Immich filters", icon="tune").classes("w-full"):
        albums_field = (
            ui.textarea("Album IDs (one per line)", value="\n".join(job.get("album_ids") or []))
            .classes("w-full")
            .props("autogrow")
        )
        persons_field = (
            ui.textarea("Person IDs (one per line)", value="\n".join(job.get("person_ids") or []))
            .classes("w-full")
            .props("autogrow")
        )
        tags_field = (
            ui.textarea("Tag IDs (one per line)", value="\n".join(job.get("tag_ids") or []))
            .classes("w-full")
            .props("autogrow")
        )
        with ui.row().classes("w-full gap-3 flex-wrap"):
            favorite_field = ui.select(
                _FAVORITE_OPTIONS, value=_bool_to_option(job.get("is_favorite")), label="Favorite filter"
            ).classes("min-w-[180px]")
            rating_field = ui.select(
                _RATING_OPTIONS,
                value=str(job["rating"]) if isinstance(job.get("rating"), int) else "",
                label="Rating",
            ).classes("min-w-[140px]")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            city_field = ui.input("City", value=job.get("city") or "").classes("flex-1 min-w-[160px]")
            state_field = ui.input("State/Region", value=job.get("state") or "").classes("flex-1 min-w-[160px]")
            country_field = ui.input("Country", value=job.get("country") or "").classes("flex-1 min-w-[160px]")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            taken_after_field = ui.input("Taken after (YYYY-MM-DD)", value=_date_str(job.get("taken_after"))).classes(
                "flex-1 min-w-[180px]"
            )
            taken_before_field = ui.input(
                "Taken before (YYYY-MM-DD)", value=_date_str(job.get("taken_before"))
            ).classes("flex-1 min-w-[180px]")
        with ui.column().classes("w-full gap-0"):
            ui.label("Minimum color score").classes("text-xs text-gray-500")
            color_slider = ui.slider(min=0.0, max=1.0, step=0.05, value=float(job.get("min_color_score") or 0.5)).props(
                "label-always"
            )
        with ui.column().classes("w-full gap-0"):
            ui.label("Minimum vibrancy score").classes("text-xs text-gray-500")
            vibrancy_slider = ui.slider(
                min=0.0, max=1.0, step=0.05, value=float(job.get("min_vibrancy_score") or 0.2)
            ).props("label-always")

    error_label = ui.label("").classes("text-red-500 text-sm")

    async def save() -> None:
        body = _collect_form(
            name=name_field.value,
            strategy=strategy_field.value or "RANDOM",
            query=query_field.value,
            target_device_id=target_field.value,
            count_raw=count_field.value,
            random_pick=bool(random_pick.value),
            overfetch=overfetch_slider.value,
            albums=albums_field.value,
            persons=persons_field.value,
            tags=tags_field.value,
            favorite=favorite_field.value,
            city=city_field.value,
            state=state_field.value,
            country=country_field.value,
            taken_after=taken_after_field.value,
            taken_before=taken_before_field.value,
            rating=rating_field.value,
            color=color_slider.value,
            vibrancy=vibrancy_slider.value,
            is_active=bool(active_switch.value),
        )
        if isinstance(body, str):
            error_label.text = body
            return
        try:
            if job_id is None:
                await api.create_sync_job(body)
            else:
                await api.update_sync_job(UUID(job_id), body)
        except ApiError as exc:
            error_label.text = f"Save failed: {exc.detail or exc}"
            return
        ui.notify("Saved", type="positive")
        ui.navigate.to("/sync-jobs")

    with ui.row().classes("w-full justify-end gap-2 pt-2"):
        ui.button("Cancel", on_click=lambda: ui.navigate.to("/sync-jobs")).props("flat")
        ui.button("Save", icon="save", on_click=save).props("color=primary")


def _collect_form(  # noqa: PLR0913, PLR0911
    *,
    name: str | None,
    strategy: str,
    query: str | None,
    target_device_id: str | None,
    count_raw: Any,
    random_pick: bool,
    overfetch: Any,
    albums: str | None,
    persons: str | None,
    tags: str | None,
    favorite: str | None,
    city: str | None,
    state: str | None,
    country: str | None,
    taken_after: str | None,
    taken_before: str | None,
    rating: str | None,
    color: Any,
    vibrancy: Any,
    is_active: bool,
) -> dict[str, Any] | str:
    if not name:
        return "Name is required"
    if not target_device_id:
        return "Target device is required"
    try:
        count = int(count_raw if count_raw is not None else 10)
    except (TypeError, ValueError):
        return "Count must be an integer"
    if not _MIN_COUNT <= count <= _MAX_COUNT:
        return f"Count must be between {_MIN_COUNT} and {_MAX_COUNT}"
    if strategy == "SMART" and not (query or "").strip():
        return "Query is required when strategy is SMART"

    parsed_after = _parse_date(taken_after)
    if taken_after and parsed_after is None:
        return "Taken-after must be YYYY-MM-DD"
    parsed_before = _parse_date(taken_before)
    if taken_before and parsed_before is None:
        return "Taken-before must be YYYY-MM-DD"

    rating_value: int | None = None
    if rating:
        try:
            rating_value = int(rating)
        except ValueError:
            return "Rating must be an integer"

    return {
        "name": name,
        "strategy": strategy,
        "query": (query or None) if strategy == "SMART" else None,
        "target_device_id": target_device_id,
        "count": count,
        "random_pick": random_pick,
        "overfetch_multiplier": int(overfetch or 3),
        "album_ids": _split_lines(albums),
        "person_ids": _split_lines(persons),
        "tag_ids": _split_lines(tags),
        "is_favorite": _option_to_bool(favorite),
        "city": city or None,
        "state": state or None,
        "country": country or None,
        "taken_after": parsed_after.isoformat() if parsed_after else None,
        "taken_before": parsed_before.isoformat() if parsed_before else None,
        "rating": rating_value,
        "min_color_score": float(color or 0.0),
        "min_vibrancy_score": float(vibrancy or 0.0),
        "is_active": is_active,
    }


def _split_lines(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [line.strip() for line in value.splitlines() if line.strip()]
    return items or None


def _option_to_bool(value: str | None) -> bool | None:
    if not value:
        return None
    return value == "true"


def _bool_to_option(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _date_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return ""


async def _load_devices(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_devices()
    except ApiError:
        logger.exception("Failed to load device list for sync-jobs view")
        return []


async def _load_device_map(api: ApiClient) -> dict[str, str]:
    devices = await _load_devices(api)
    return {d["id"]: d.get("device_id") or d["id"] for d in devices}


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("color=primary")
    result = await dialog
    return bool(result)
