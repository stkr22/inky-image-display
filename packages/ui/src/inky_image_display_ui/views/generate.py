"""On-demand AI image generation form.

End-user types a short subject, picks a target device + preset + orientation,
and submits. The API runs Gemini in a background task and (if the device is
online) pushes the result over MQTT as soon as it's ready.
"""

from __future__ import annotations

import logging
from typing import Any

from nicegui import ui

from inky_image_display_ui.api_client import ApiClient, ApiError
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._ui import tile as bento_tile

logger = logging.getLogger(__name__)


def register() -> None:
    """Register the /generate route."""

    @ui.page("/generate")
    async def page() -> None:
        with frame("/generate"):
            await _render()


async def _render() -> None:
    api = require_api_client()
    profiles = await _profiles(api)
    presets = await _presets(api)

    profile_options = {p["id"]: f"{p['name']} ({p['width']}x{p['height']})" for p in profiles}
    default_profile_id = next(
        (p["id"] for p in profiles if p.get("is_default")),
        next(iter(profile_options), None),
    )
    preset_options = {p["id"]: p["name"] for p in presets}
    default_preset_id = next(
        (p["id"] for p in presets if p.get("is_default")),
        next(iter(preset_options), None),
    )

    with ui.column().classes("gap-0"):
        ui.label("AI generation").classes("ink-eyebrow")
        ui.label("Generate an image").classes("ink-h2")
        ui.label(
            "Type a subject — the API renders it with Gemini and dispatches the result "
            "to a random matching device as soon as it's ready."
        ).classes("ink-body ink-muted").style("max-width: 640px;")

    with (
        ui.element("div").classes("bento-tile w-full").style("padding: 24px;"),
        ui.column().classes("w-full ink-form-section"),
    ):
        subject_field = (
            ui.input("Subject", placeholder="e.g. Ada Lovelace, a fox in a forest…")
            .classes("w-full")
            .props("outlined autofocus")
        )
        profile_field = (
            ui.select(
                profile_options,
                value=default_profile_id,
                label="Target device profile",
            )
            .classes("w-full")
            .props("outlined")
        )
        preset_field = (
            ui.select(preset_options, value=default_preset_id, label="Prompt preset")
            .classes("w-full")
            .props("outlined")
        )
        with ui.row().classes("w-full ink-form-row items-center"):
            portrait_switch = ui.switch("Portrait orientation", value=True)
            push_switch = ui.switch("Push immediately when ready", value=True)

    error_label = ui.label("").style("color: var(--ink-danger); font-size: 13px;")

    async def submit() -> None:
        if not subject_field.value:
            error_label.text = "Subject is required"
            return
        if not profile_field.value:
            error_label.text = "Target device profile is required"
            return
        body = {
            "subject": subject_field.value,
            "target_device_profile_id": profile_field.value,
            "preset_id": preset_field.value,
            "orientation": "portrait" if portrait_switch.value else "landscape",
            "push_immediately": bool(push_switch.value),
        }
        try:
            result = await api.generate_image(body)
        except ApiError as exc:
            error_label.text = f"Generation failed: {exc.detail or exc}"
            return
        ui.notify(
            f"Queued (task {result.get('task_id')}) — image will appear shortly.",
            type="positive",
        )
        subject_field.value = ""

    with ui.element("div").classes("ink-action-bar w-full"):
        ui.button("Generate", icon="auto_awesome", on_click=submit).props("unelevated color=primary")


async def _profiles(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_device_profiles()
    except ApiError:
        return []


async def _presets(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_prompt_presets()
    except ApiError:
        return []


async def tile() -> None:
    """Quick-action card on the landing dashboard."""
    with bento_tile(span="col-span-4", href="/generate"):
        ui.label("AI generation").classes("ink-eyebrow")
        ui.label("Generate now").classes("ink-h3")
        ui.label("Make a one-off image with Gemini.").classes("ink-small")


__all__ = ["register", "tile"]
