"""Unified GenAI page: on-demand generation form + prompt library.

Layout intent:
- Generate form sits on top — that's why end-users land here.
- The prompt library is power-user territory; it's tucked into an
  "Advanced" expansion below so the page stays focused at first glance.
- Within the library, blocks render as a compact list (kind chip, name,
  default toggle, edit/delete) with the long block text revealed inside a
  per-row expansion, so the page no longer dumps every paragraph at once.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import ui

from inky_image_display_ui.api_client import ApiClient, ApiError
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame

logger = logging.getLogger(__name__)

_KINDS = ["style", "palette", "legibility", "composition", "background"]
_SUBJECT_MAX_CHARS = 200
_BLOCK_PREVIEW_CHARS = 80


def register() -> None:
    """Register the /genai route."""

    @ui.page("/genai")
    async def page() -> None:
        with frame("/genai"):
            await _render()


async def _render() -> None:
    api = require_api_client()
    profiles = await _list_device_profiles(api)
    presets = await api.list_prompt_presets()
    blocks = await api.list_prompt_blocks()

    _render_generate_section(api, profiles, presets)

    ui.element("div").style("height: 24px;")

    _render_advanced_section(api, blocks, presets)


# --- Generate ---


def _render_generate_section(
    api: ApiClient,
    profiles: list[dict[str, Any]],
    presets: list[dict[str, Any]],
) -> None:
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
        ui.label("GenAI").classes("ink-eyebrow")
        ui.label("Generate an image").classes("ink-h2")
        ui.label(
            "Describe what you want to see. The API renders it with Gemini "
            "and dispatches the result to a random matching device as soon as it's ready."
        ).classes("ink-body ink-muted").style("max-width: 640px;")

    with (
        ui.element("div").classes("bento-tile w-full").style("padding: 24px;"),
        ui.column().classes("w-full ink-form-section"),
    ):
        subject_field = (
            ui.textarea(
                "Subject",
                placeholder="e.g. Ada Lovelace, a fox in a snowy forest, "
                "a vintage espresso machine on a kitchen counter…",
            )
            .classes("w-full")
            .props(f"outlined autofocus maxlength={_SUBJECT_MAX_CHARS} counter rows=4")
            .style("font-size: 15px;")
        )
        with ui.row().classes("w-full ink-form-row"):
            profile_field = (
                ui.select(
                    profile_options,
                    value=default_profile_id,
                    label="Target device profile",
                )
                .classes("flex-1")
                .props("outlined")
            )
            preset_field = (
                ui.select(preset_options, value=default_preset_id, label="Prompt preset")
                .classes("flex-1")
                .props("outlined")
            )
        with ui.row().classes("w-full ink-form-row items-center"):
            portrait_switch = ui.switch("Portrait orientation", value=True)
            push_switch = ui.switch("Push immediately when ready", value=True)

    error_label = ui.label("").style("color: var(--ink-danger); font-size: 13px;")

    async def submit() -> None:
        if not subject_field.value or not subject_field.value.strip():
            error_label.text = "Subject is required"
            return
        if len(subject_field.value) > _SUBJECT_MAX_CHARS:
            error_label.text = f"Subject must be at most {_SUBJECT_MAX_CHARS} characters"
            return
        if not profile_field.value:
            error_label.text = "Target device profile is required"
            return
        body = {
            "subject": subject_field.value.strip(),
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
        error_label.text = ""

    with ui.element("div").classes("ink-action-bar w-full"):
        ui.button("Generate", icon="auto_awesome", on_click=submit).props("unelevated color=primary")


# --- Advanced: prompt library ---


def _render_advanced_section(
    api: ApiClient,
    blocks: list[dict[str, Any]],
    presets: list[dict[str, Any]],
) -> None:
    blocks_state: list[dict[str, Any]] = list(blocks)
    presets_state: list[dict[str, Any]] = list(presets)

    with ui.expansion("Advanced — prompt library", icon="settings").classes("w-full"):
        ui.label(
            "Power-user controls. Blocks are the reusable text fragments that "
            "make up a preset; presets are what the generate form and Gemini "
            "batch jobs reference. Composition blocks may include {subject}."
        ).classes("ink-small").style("margin-bottom: 8px;")
        # Create the container inside the expansion so its children stay scoped.
        container = ui.column().classes("w-full gap-3")

    async def reload() -> None:
        try:
            blocks_state.clear()
            blocks_state.extend(await api.list_prompt_blocks())
            presets_state.clear()
            presets_state.extend(await api.list_prompt_presets())
        except ApiError as exc:
            ui.notify(f"Reload failed: {exc.detail or exc}", type="negative")
            return
        rerender()

    def rerender() -> None:
        container.clear()
        with container:
            _render_block_table(api, blocks_state, reload)
            _render_preset_table(api, presets_state, blocks_state, reload)

    rerender()


def _render_block_table(
    api: ApiClient,
    blocks: list[dict[str, Any]],
    reload: Any,
) -> None:
    with ui.element("div").classes("bento-tile w-full").style("padding: 20px;"):
        ui.label("Blocks").classes("ink-h3")
        if not blocks:
            ui.label("(none)").classes("ink-small")
        for block in sorted(blocks, key=lambda b: (b["kind"], b["name"])):
            _render_block_row(api, block, reload)

        ui.separator().style("margin: 12px 0;")
        _render_new_block_form(api, reload)


def _render_block_row(api: ApiClient, block: dict[str, Any], reload: Any) -> None:
    block_id = UUID(block["id"])
    default_marker = " · default" if block.get("is_default") else ""
    preview = block["text"][:_BLOCK_PREVIEW_CHARS] + ("…" if len(block["text"]) > _BLOCK_PREVIEW_CHARS else "")
    header = f"{block['kind'].upper()}  ·  {block['name']}{default_marker}"

    with (
        ui.expansion(header)
        .classes("w-full")
        .style("border: 1px solid var(--ink-border); border-radius: 10px; margin-bottom: 6px;"),
    ):
        ui.label(preview).classes("ink-small").style("margin-bottom: 8px;")
        name = ui.input("Name", value=block["name"]).classes("w-full").props("outlined dense")
        text = ui.textarea("Text", value=block["text"]).classes("w-full").props("outlined autogrow")
        default = ui.switch("Use as default for this kind", value=bool(block.get("is_default")))

        async def save() -> None:
            try:
                await api.update_prompt_block(
                    block_id,
                    {"name": name.value, "text": text.value, "is_default": bool(default.value)},
                )
            except ApiError as exc:
                ui.notify(f"Save failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Saved", type="positive")
            await reload()

        async def delete() -> None:
            try:
                await api.delete_prompt_block(block_id)
            except ApiError as exc:
                ui.notify(f"Delete failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Deleted", type="positive")
            await reload()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Save", icon="save", on_click=save).props("flat color=primary")
            ui.button("Delete", icon="delete", on_click=delete).props("flat color=negative")


def _render_new_block_form(api: ApiClient, reload: Any) -> None:
    with ui.expansion("Add new block", icon="add").classes("w-full"):
        kind_field = ui.select(_KINDS, value="style", label="Kind").classes("w-full").props("outlined")
        name_field = ui.input("Name").classes("w-full").props("outlined")
        text_field = ui.textarea("Text").classes("w-full").props("outlined autogrow")

        async def create() -> None:
            if not name_field.value or not text_field.value:
                ui.notify("Name and text are required", type="warning")
                return
            try:
                await api.create_prompt_block(
                    {
                        "kind": kind_field.value,
                        "name": name_field.value,
                        "text": text_field.value,
                        "is_default": False,
                    }
                )
            except ApiError as exc:
                ui.notify(f"Create failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Created", type="positive")
            await reload()

        ui.button("Add block", icon="add", on_click=create).props("unelevated color=primary")


def _render_preset_table(
    api: ApiClient,
    presets: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    reload: Any,
) -> None:
    blocks_by_kind: dict[str, list[dict[str, Any]]] = {k: [] for k in _KINDS}
    for b in blocks:
        if b["kind"] in blocks_by_kind:
            blocks_by_kind[b["kind"]].append(b)
    block_name_by_id = {b["id"]: b["name"] for b in blocks}

    with ui.element("div").classes("bento-tile w-full").style("padding: 20px;"):
        ui.label("Presets").classes("ink-h3")
        if not presets:
            ui.label("(none)").classes("ink-small")
        for preset in presets:
            _render_preset_row(api, preset, blocks_by_kind, block_name_by_id, reload)

        ui.separator().style("margin: 12px 0;")
        _render_new_preset_form(api, blocks_by_kind, reload)


def _render_preset_row(
    api: ApiClient,
    preset: dict[str, Any],
    blocks_by_kind: dict[str, list[dict[str, Any]]],
    block_name_by_id: dict[str, str],
    reload: Any,
) -> None:
    preset_id = UUID(preset["id"])
    default_marker = " · default" if preset.get("is_default") else ""
    summary = " / ".join(block_name_by_id.get(preset[f"{kind}_block_id"], "?") for kind in _KINDS)
    header = f"{preset['name']}{default_marker}"

    with (
        ui.expansion(header)
        .classes("w-full")
        .style("border: 1px solid var(--ink-border); border-radius: 10px; margin-bottom: 6px;"),
    ):
        ui.label(summary).classes("ink-small").style("margin-bottom: 8px;")
        name = ui.input("Name", value=preset["name"]).classes("w-full").props("outlined dense")
        model = (
            ui.input(
                "Gemini model",
                value=preset.get("model_name") or "gemini-2.5-flash-image",
            )
            .classes("w-full")
            .props("outlined dense")
        )
        selectors: dict[str, Any] = {}
        for kind in _KINDS:
            options = {b["id"]: b["name"] for b in blocks_by_kind[kind]}
            selectors[kind] = (
                ui.select(options, value=preset[f"{kind}_block_id"], label=kind.capitalize())
                .classes("w-full")
                .props("outlined")
            )
        is_default = ui.switch("Default preset", value=bool(preset.get("is_default")))

        async def save() -> None:
            try:
                await api.update_prompt_preset(
                    preset_id,
                    {
                        "name": name.value,
                        "model_name": model.value or "gemini-2.5-flash-image",
                        **{f"{k}_block_id": selectors[k].value for k in _KINDS},
                        "is_default": bool(is_default.value),
                    },
                )
            except ApiError as exc:
                ui.notify(f"Save failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Saved", type="positive")
            await reload()

        async def delete() -> None:
            try:
                await api.delete_prompt_preset(preset_id)
            except ApiError as exc:
                ui.notify(f"Delete failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Deleted", type="positive")
            await reload()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Save", icon="save", on_click=save).props("flat color=primary")
            ui.button("Delete", icon="delete", on_click=delete).props("flat color=negative")


def _render_new_preset_form(
    api: ApiClient,
    blocks_by_kind: dict[str, list[dict[str, Any]]],
    reload: Any,
) -> None:
    with ui.expansion("Add new preset", icon="add").classes("w-full"):
        name_field = ui.input("Name").classes("w-full").props("outlined")
        model_field = ui.input("Gemini model", value="gemini-2.5-flash-image").classes("w-full").props("outlined")
        selectors: dict[str, Any] = {}
        for kind in _KINDS:
            options = {b["id"]: b["name"] for b in blocks_by_kind[kind]}
            default_id = next(
                (b["id"] for b in blocks_by_kind[kind] if b.get("is_default")),
                next(iter(options), None),
            )
            selectors[kind] = (
                ui.select(options, value=default_id, label=kind.capitalize()).classes("w-full").props("outlined")
            )
        is_default = ui.switch("Make default", value=False)

        async def create() -> None:
            if not name_field.value:
                ui.notify("Name is required", type="warning")
                return
            if any(selectors[k].value is None for k in _KINDS):
                ui.notify("All five blocks must be selected", type="warning")
                return
            try:
                await api.create_prompt_preset(
                    {
                        "name": name_field.value,
                        "model_name": model_field.value or "gemini-2.5-flash-image",
                        **{f"{k}_block_id": selectors[k].value for k in _KINDS},
                        "is_default": bool(is_default.value),
                    }
                )
            except ApiError as exc:
                ui.notify(f"Create failed: {exc.detail or exc}", type="negative")
                return
            ui.notify("Created", type="positive")
            await reload()

        ui.button("Add preset", icon="add", on_click=create).props("unelevated color=primary")


async def _list_device_profiles(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_device_profiles()
    except ApiError:
        return []


__all__ = ["register"]
