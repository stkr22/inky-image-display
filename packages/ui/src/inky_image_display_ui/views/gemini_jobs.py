"""Gemini batch sync jobs view: list + create/edit form."""

from __future__ import annotations

import logging
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


def register() -> None:
    """Register Gemini sync-job create/edit routes.

    The listing moved to ``/jobs?tab=gemini``; these routes only handle the
    forms. Bare ``/gemini-jobs`` redirects to the unified listing.
    """

    @ui.page("/gemini-jobs")
    async def list_redirect() -> None:
        ui.navigate.to("/jobs?tab=gemini")

    @ui.page("/gemini-jobs/new")
    async def create_page() -> None:
        with frame("/jobs"):
            await _render_form(job_id=None)

    @ui.page("/gemini-jobs/{job_id}")
    async def edit_page(job_id: str) -> None:
        with frame("/jobs"):
            await _render_form(job_id=job_id)


async def _render_list() -> None:
    api = require_api_client()
    profile_map = await _profile_map(api)

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("AI generation").classes("ink-eyebrow")
            ui.label("Gemini jobs").classes("ink-h2")
        with ui.row().classes("items-center gap-2"):
            refresh = ui.button(icon="refresh").props("flat round").tooltip("Refresh")
            ui.button(
                "New job",
                icon="add",
                on_click=lambda: ui.navigate.to("/gemini-jobs/new"),
            ).props("color=primary unelevated")

    container = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        try:
            jobs = await api.list_gemini_jobs()
        except ApiError as exc:
            ui.notify(f"Failed to load Gemini jobs: {exc.detail or exc}", type="negative")
            return
        container.clear()
        with container:
            if not jobs:
                ui.label("No Gemini jobs yet.").classes("italic text-gray-500")
                return
            for job in jobs:
                _render_row(api, job, profile_map, reload)

    refresh.on_click(reload)
    await reload()


def _render_row(
    api: ApiClient,
    job: dict[str, Any],
    profile_map: dict[str, str],
    on_changed: Any,
) -> None:
    job_id = UUID(job["id"])
    target_name = profile_map.get(job["target_device_profile_id"], job["target_device_profile_id"])
    total = len(job.get("subjects") or []) * int(job.get("images_per_subject") or 1)
    orientation = job.get("orientation") or "portrait"

    async def toggle_active(e: events.ValueChangeEventArguments) -> None:
        new_value = bool(e.value)
        try:
            await api.update_gemini_job(job_id, {"is_active": new_value})
        except ApiError as exc:
            ui.notify(f"Toggle failed: {exc.detail or exc}", type="negative")
            switch.value = not new_value
            return
        ui.notify("Updated", type="positive")

    async def delete() -> None:
        try:
            await api.delete_gemini_job(job_id)
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
            ui.label(job["name"]).classes("ink-h3")
            ui.label(f"{orientation} · {total} images per run · → {target_name}").classes("ink-small")
            ui.label(f"Updated {format_datetime(job.get('updated_at'))}").classes("ink-small")
        switch = ui.switch(value=bool(job.get("is_active"))).tooltip("Active")
        switch.on_value_change(toggle_active)
        ui.button(icon="edit", on_click=lambda jid=job["id"]: ui.navigate.to(f"/gemini-jobs/{jid}")).props(
            "flat round"
        ).tooltip("Edit")
        ui.button(icon="delete", on_click=delete).props("flat round color=negative").tooltip("Delete")


async def _render_form(*, job_id: str | None) -> None:  # noqa: PLR0915
    api = require_api_client()
    profiles = await _profiles(api)
    presets = await _presets(api)

    profile_options = {p["id"]: f"{p['name']} ({p['width']}x{p['height']})" for p in profiles}
    preset_options = {p["id"]: p["name"] for p in presets}
    orientation_options = {"portrait": "Portrait", "landscape": "Landscape"}

    job: dict[str, Any] = {}
    if job_id is not None:
        try:
            job = await api.get_gemini_job(UUID(job_id))
        except ApiError as exc:
            ui.notify(f"Load failed: {exc.detail or exc}", type="negative")
            return

    eyebrow = "AI generation / new" if job_id is None else "AI generation / edit"
    title = "New Gemini job" if job_id is None else "Edit Gemini job"
    with ui.row().classes("w-full items-center gap-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/jobs?tab=gemini")).props("flat round")
        with ui.column().classes("gap-0"):
            ui.label(eyebrow).classes("ink-eyebrow")
            ui.label(title).classes("ink-h2")

    default_preset_id = next(
        (p["id"] for p in presets if p.get("is_default")),
        next(iter(preset_options), None),
    )

    with (
        ui.element("div").classes("bento-tile w-full").style("padding: 24px;"),
        ui.column().classes("w-full ink-form-section"),
    ):
        name_field = ui.input("Name", value=job.get("name") or "").classes("w-full").props("outlined")
        target_field = (
            ui.select(
                profile_options,
                value=job.get("target_device_profile_id") or (profiles[0]["id"] if profiles else None),
                label="Target device profile",
            )
            .classes("w-full")
            .props("outlined")
        )
        preset_field = (
            ui.select(
                preset_options,
                value=job.get("prompt_preset_id") or default_preset_id,
                label="Prompt preset",
            )
            .classes("w-full")
            .props("outlined")
        )
        with ui.row().classes("w-full ink-form-row items-center"):
            orientation_field = (
                ui.select(
                    orientation_options,
                    value=job.get("orientation") or "portrait",
                    label="Orientation",
                )
                .classes("flex-1")
                .props("outlined")
            )
            images_field = (
                ui.number(
                    "Images per subject",
                    value=int(job.get("images_per_subject") or 1),
                    min=1,
                    max=10,
                    step=1,
                )
                .classes("flex-1")
                .props("outlined")
            )
            retention_field = (
                ui.number(
                    "Retention (days, blank = forever)",
                    value=int(job["retention_days"]) if isinstance(job.get("retention_days"), int) else None,
                    min=0,
                    step=1,
                )
                .classes("flex-1")
                .props("outlined clearable")
            )
        subjects_field = (
            ui.select(
                options=list(job.get("subjects") or []),
                value=list(job.get("subjects") or []),
                label="Subjects",
                multiple=True,
                new_value_mode="add-unique",
            )
            .classes("w-full")
            .props("outlined use-chips use-input hide-dropdown-icon")
        )
        active_switch = ui.switch("Active", value=bool(job.get("is_active", True)))

    error_label = ui.label("").style("color: var(--ink-danger); font-size: 13px;")

    async def save() -> None:
        if not name_field.value:
            error_label.text = "Name is required"
            return
        if not target_field.value:
            error_label.text = "Target device profile is required"
            return
        if not preset_field.value:
            error_label.text = "Preset is required"
            return
        subjects = [s.strip() for s in (subjects_field.value or []) if isinstance(s, str) and s.strip()]
        if not subjects:
            error_label.text = "At least one subject is required"
            return
        body = {
            "name": name_field.value,
            "is_active": bool(active_switch.value),
            "target_device_profile_id": target_field.value,
            "prompt_preset_id": preset_field.value,
            "orientation": orientation_field.value or "portrait",
            "subjects": subjects,
            "images_per_subject": int(images_field.value or 1),
            "retention_days": int(retention_field.value) if retention_field.value is not None else None,
        }
        try:
            if job_id is None:
                await api.create_gemini_job(body)
            else:
                await api.update_gemini_job(UUID(job_id), body)
        except ApiError as exc:
            error_label.text = f"Save failed: {exc.detail or exc}"
            return
        ui.notify("Saved", type="positive")
        ui.navigate.to("/jobs?tab=gemini")

    with ui.element("div").classes("ink-action-bar w-full"):
        ui.button("Cancel", on_click=lambda: ui.navigate.to("/jobs?tab=gemini")).props("flat")
        ui.button("Save", icon="save", on_click=save).props("unelevated color=primary")


async def tile() -> None:
    """Render the Gemini jobs bento tile on the landing dashboard."""
    api = require_api_client()
    try:
        jobs = await api.list_gemini_jobs()
    except ApiError:
        logger.exception("list_gemini_jobs failed on landing tile")
        jobs = []
    total = len(jobs)
    active = sum(1 for j in jobs if j.get("is_active"))
    with bento_tile(span="col-span-4", href="/gemini-jobs"):
        stat(label="Gemini jobs", value=f"{active}/{total}", hint="Active / configured")


async def _profiles(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_device_profiles()
    except ApiError:
        return []


async def _profile_map(api: ApiClient) -> dict[str, str]:
    return {p["id"]: p["name"] for p in await _profiles(api)}


async def _presets(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_prompt_presets()
    except ApiError:
        return []


__all__ = ["register", "tile"]
