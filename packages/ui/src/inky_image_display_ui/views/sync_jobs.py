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
from inky_image_display_ui.views._ui import stat
from inky_image_display_ui.views._ui import tile as bento_tile

logger = logging.getLogger(__name__)

_STRATEGIES = ["RANDOM", "SMART"]
_MIN_COUNT = 1
_MAX_COUNT = 1000
_FAVORITE_OPTIONS: dict[str, str] = {"": "Any", "true": "Favorites only", "false": "Non-favorites only"}
_RATING_OPTIONS: dict[str, str] = {"": "Any", **{str(i): f">= {i}" for i in range(6)}}


def register() -> None:
    """Register Immich sync-job create/edit routes.

    The listing has moved to ``/jobs`` (tabbed); these routes only handle the
    forms. Bare ``/sync-jobs`` redirects to the unified listing.
    """

    @ui.page("/sync-jobs")
    async def list_redirect() -> None:
        ui.navigate.to("/jobs")

    @ui.page("/sync-jobs/new")
    async def create_page() -> None:
        with frame("/jobs"):
            await _render_form(job_id=None)

    @ui.page("/sync-jobs/{job_id}")
    async def edit_page(job_id: str) -> None:
        with frame("/jobs"):
            await _render_form(job_id=job_id)


async def _render_list() -> None:
    api = require_api_client()
    profile_map = await _load_profile_map(api)

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Automations").classes("ink-eyebrow")
            ui.label("Sync jobs").classes("ink-h2")
        with ui.row().classes("items-center gap-2"):
            refresh_button = ui.button(icon="refresh").props("flat round").tooltip("Refresh")
            ui.button("New job", icon="add", on_click=lambda: ui.navigate.to("/sync-jobs/new")).props(
                "color=primary unelevated"
            )

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
                _render_row(api, job, profile_map, reload)

    refresh_button.on_click(reload)
    await reload()


def _render_row(api: ApiClient, job: dict[str, Any], profile_map: dict[str, str], on_changed: Any) -> None:
    job_id = UUID(job["id"])
    target_name = profile_map.get(job["target_device_profile_id"], job["target_device_profile_id"])
    orientation = job.get("orientation") or "any orientation"

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

    with (
        ui.element("div")
        .classes("bento-tile w-full")
        .style("padding: 16px 20px; flex-direction: row; align-items: center; gap: 12px;"),
    ):
        with ui.column().classes("flex-1 gap-1 min-w-0"):
            ui.label(job["name"]).classes("ink-h3").style(
                "white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
            )
            ui.label(f"{job['strategy']} · count {job['count']} · → {target_name} · {orientation}").classes("ink-small")
            ui.label(f"Updated {format_datetime(job.get('updated_at'))}").classes("ink-small")
        switch = ui.switch(value=bool(job.get("is_active"))).tooltip("Active")
        switch.on_value_change(toggle_active)
        ui.button(icon="edit", on_click=lambda jid=job["id"]: ui.navigate.to(f"/sync-jobs/{jid}")).props(
            "flat round"
        ).tooltip("Edit")
        ui.button(icon="delete", on_click=delete).props("flat round color=negative").tooltip("Delete")


async def _render_form(*, job_id: str | None) -> None:  # noqa: PLR0915
    api = require_api_client()
    profiles = await _load_profiles(api)
    profile_options: dict[str, str] = {p["id"]: f"{p['name']} ({p['width']}x{p['height']})" for p in profiles}
    orientation_options: dict[str, str] = {"": "Any orientation", "landscape": "Landscape", "portrait": "Portrait"}

    job: dict[str, Any] = {}
    if job_id is not None:
        try:
            job = await api.get_sync_job(UUID(job_id))
        except ApiError as exc:
            ui.notify(f"Load failed: {exc.detail or exc}", type="negative")
            ui.label("Could not load sync job.").classes("text-red-500")
            return

    eyebrow = "Automations / new" if job_id is None else "Automations / edit"
    title = "New sync job" if job_id is None else "Edit sync job"
    with ui.row().classes("w-full items-center gap-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/jobs")).props("flat round").tooltip(
            "Back to sync jobs"
        )
        with ui.column().classes("gap-0"):
            ui.label(eyebrow).classes("ink-eyebrow")
            ui.label(title).classes("ink-h2")

    # --- Basics card ---------------------------------------------------------
    with (
        ui.element("div").classes("bento-tile w-full").style("padding: 24px;"),
        ui.column().classes("w-full ink-form-section"),
    ):
        ui.label("Basics").classes("ink-eyebrow")
        name_field = ui.input("Name", value=job.get("name") or "").classes("w-full").props("outlined")
        with ui.row().classes("w-full ink-form-row"):
            strategy_field = (
                ui.select(_STRATEGIES, value=job.get("strategy") or "RANDOM", label="Strategy")
                .classes("flex-1")
                .props("outlined")
            )
            query_field = (
                ui.input("Query (SMART only)", value=job.get("query") or "").classes("flex-1").props("outlined")
            )
        target_field = (
            ui.select(
                profile_options,
                value=job.get("target_device_profile_id") or (profiles[0]["id"] if profiles else None),
                label="Target device profile",
            )
            .classes("w-full")
            .props("outlined")
        )
        orientation_field = (
            ui.select(
                orientation_options,
                value=job.get("orientation") or "",
                label="Orientation override",
            )
            .classes("w-full")
            .props("outlined")
        )
        with ui.row().classes("w-full ink-form-row items-end"):
            count_field = (
                ui.number(
                    "Count (1-1000)",
                    value=int(job.get("count") or 10),
                    min=_MIN_COUNT,
                    max=_MAX_COUNT,
                    step=1,
                )
                .classes("flex-1")
                .props("outlined")
            )
            with ui.column().classes("flex-1 gap-1 min-w-[180px]"):
                with ui.row().classes("w-full items-baseline justify-between"):
                    ui.label("Overfetch multiplier").classes("ink-small")
                    overfetch_value = ui.label().classes("ink-slider-value")
                overfetch_slider = ui.slider(min=1, max=10, step=1, value=int(job.get("overfetch_multiplier") or 3))
                overfetch_value.bind_text_from(overfetch_slider, "value")
        with ui.row().classes("w-full gap-4 items-center flex-wrap"):
            random_pick = ui.switch("Random pick", value=bool(job.get("random_pick")))
            active_switch = ui.switch("Active", value=bool(job.get("is_active", True)))

    def _refresh_query_enabled() -> None:
        query_field.set_enabled(strategy_field.value == "SMART")

    strategy_field.on_value_change(lambda _e: _refresh_query_enabled())
    _refresh_query_enabled()

    # --- Immich filters card -------------------------------------------------
    with (
        ui.element("div").classes("bento-tile w-full").style("padding: 24px;"),
        ui.column().classes("w-full ink-form-section"),
    ):
        ui.label("Immich filters").classes("ink-eyebrow")
        ui.label("Narrow which photos the sync pulls").classes("ink-small")

        with ui.row().classes("w-full ink-form-row"):
            albums_field = (
                ui.textarea("Album IDs (one per line)", value="\n".join(job.get("album_ids") or []))
                .classes("flex-1")
                .props("outlined autogrow")
            )
            persons_field = (
                ui.textarea("Person IDs (one per line)", value="\n".join(job.get("person_ids") or []))
                .classes("flex-1")
                .props("outlined autogrow")
            )
            tags_field = (
                ui.textarea("Tag IDs (one per line)", value="\n".join(job.get("tag_ids") or []))
                .classes("flex-1")
                .props("outlined autogrow")
            )
        with ui.row().classes("w-full ink-form-row"):
            favorite_field = (
                ui.select(_FAVORITE_OPTIONS, value=_bool_to_option(job.get("is_favorite")), label="Favorite filter")
                .classes("flex-1")
                .props("outlined")
            )
            rating_field = (
                ui.select(
                    _RATING_OPTIONS,
                    value=str(job["rating"]) if isinstance(job.get("rating"), int) else "",
                    label="Rating",
                )
                .classes("flex-1")
                .props("outlined")
            )
        with ui.row().classes("w-full ink-form-row"):
            city_field = ui.input("City", value=job.get("city") or "").classes("flex-1").props("outlined")
            state_field = ui.input("State/Region", value=job.get("state") or "").classes("flex-1").props("outlined")
            country_field = ui.input("Country", value=job.get("country") or "").classes("flex-1").props("outlined")
        with ui.row().classes("w-full ink-form-row"):
            taken_after_field = (
                ui.input("Taken after (YYYY-MM-DD)", value=_date_str(job.get("taken_after")))
                .classes("flex-1")
                .props("outlined")
            )
            taken_before_field = (
                ui.input("Taken before (YYYY-MM-DD)", value=_date_str(job.get("taken_before")))
                .classes("flex-1")
                .props("outlined")
            )
    error_label = ui.label("").style("color: var(--ink-danger); font-size: 13px;")

    async def save() -> None:
        body = _collect_form(
            name=name_field.value,
            strategy=strategy_field.value or "RANDOM",
            query=query_field.value,
            target_device_profile_id=target_field.value,
            orientation=orientation_field.value or None,
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
        ui.navigate.to("/jobs")

    with ui.element("div").classes("ink-action-bar w-full"):
        ui.button("Cancel", on_click=lambda: ui.navigate.to("/jobs")).props("flat")
        ui.button("Save", icon="save", on_click=save).props("unelevated color=primary")


def _collect_form(  # noqa: PLR0913, PLR0911
    *,
    name: str | None,
    strategy: str,
    query: str | None,
    target_device_profile_id: str | None,
    orientation: str | None,
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
    is_active: bool,
) -> dict[str, Any] | str:
    if not name:
        return "Name is required"
    if not target_device_profile_id:
        return "Target device profile is required"
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
        "target_device_profile_id": target_device_profile_id,
        "orientation": orientation,
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


async def tile() -> None:
    """Render the Sync jobs bento tile on the landing dashboard."""
    api = require_api_client()
    try:
        jobs = await api.list_sync_jobs()
    except ApiError:
        logger.exception("list_sync_jobs failed on landing tile")
        jobs = []
    total = len(jobs)
    active = sum(1 for j in jobs if j.get("is_active"))

    with bento_tile(span="col-span-4", href="/sync-jobs"):
        stat(label="Sync jobs", value=f"{active}/{total}", hint="Active / configured")


async def _load_profiles(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_device_profiles()
    except ApiError:
        logger.exception("Failed to load device profiles for sync-jobs view")
        return []


async def _load_profile_map(api: ApiClient) -> dict[str, str]:
    profiles = await _load_profiles(api)
    return {p["id"]: p["name"] for p in profiles}


async def _confirm(message: str) -> bool:
    with ui.dialog() as dialog, ui.card().style("padding: 20px; gap: 12px; min-width: 320px;"):
        ui.label(message).classes("ink-body")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Confirm", on_click=lambda: dialog.submit(True)).props("unelevated color=primary")
    result = await dialog
    return bool(result)
