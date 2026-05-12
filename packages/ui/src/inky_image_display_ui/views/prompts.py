"""Prompt blocks + presets editor.

Single page split in two: the upper card lists prompt blocks (the reusable
text fragments per concern: style/palette/legibility/composition/background)
with inline edit; the lower card lists presets (a bundle of one block per
concern) with dropdowns to pick which block fills each slot.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nicegui import ui

from inky_image_display_ui.api_client import ApiClient, ApiError
from inky_image_display_ui.session import require_api_client
from inky_image_display_ui.views._layout import frame
from inky_image_display_ui.views._ui import stat
from inky_image_display_ui.views._ui import tile as bento_tile

logger = logging.getLogger(__name__)

_KINDS = ["style", "palette", "legibility", "composition", "background"]


def register() -> None:
    """Register the prompts page route."""

    @ui.page("/prompts")
    async def page() -> None:
        with frame("/prompts"):
            await _render()


async def _render() -> None:
    api = require_api_client()

    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("AI generation").classes("ink-eyebrow")
            ui.label("Prompts").classes("ink-h2")
        ui.button(icon="refresh", on_click=lambda: ui.navigate.to("/prompts")).props("flat round").tooltip("Reload")

    container_blocks = ui.column().classes("w-full gap-2")
    container_presets = ui.column().classes("w-full gap-2")

    async def reload() -> None:
        try:
            blocks = await api.list_prompt_blocks()
            presets = await api.list_prompt_presets()
        except ApiError as exc:
            ui.notify(f"Load failed: {exc.detail or exc}", type="negative")
            return
        _render_blocks(api, blocks, container_blocks, reload)
        _render_presets(api, presets, blocks, container_presets, reload)

    await reload()


def _render_blocks(
    api: ApiClient,
    blocks: list[dict[str, Any]],
    container: ui.column,
    reload: Any,
) -> None:
    container.clear()
    with container:
        ui.label("Blocks").classes("ink-h3")
        ui.label("Reusable text fragments. Composition blocks may use {subject}.").classes("ink-small")

        with (
            ui.element("div").classes("bento-tile w-full").style("padding: 16px;"),
            ui.column().classes("w-full gap-3"),
        ):
            for kind in _KINDS:
                ui.label(kind.upper()).classes("ink-eyebrow")
                kind_blocks = [b for b in blocks if b["kind"] == kind]
                if not kind_blocks:
                    ui.label("(none)").classes("ink-small")
                for block in kind_blocks:
                    _render_block_row(api, block, reload)

            ui.separator()
            ui.label("Add new block").classes("ink-eyebrow")
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


def _render_block_row(api: ApiClient, block: dict[str, Any], reload: Any) -> None:
    block_id = UUID(block["id"])

    style = (
        "border: 1px solid var(--ink-border); border-radius: 12px; "
        "padding: 12px; display: flex; flex-direction: column; gap: 8px;"
    )
    with ui.element("div").classes("w-full").style(style):
        with ui.row().classes("w-full items-center gap-2"):
            name = ui.input(value=block["name"]).classes("flex-1").props("outlined dense")
            default = ui.switch("Default", value=bool(block.get("is_default")))
        text = ui.textarea(value=block["text"]).classes("w-full").props("outlined autogrow")

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


def _render_presets(
    api: ApiClient,
    presets: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    container: ui.column,
    reload: Any,
) -> None:
    container.clear()
    blocks_by_kind: dict[str, list[dict[str, Any]]] = {k: [] for k in _KINDS}
    for b in blocks:
        if b["kind"] in blocks_by_kind:
            blocks_by_kind[b["kind"]].append(b)

    with container:
        ui.label("Presets").classes("ink-h3")
        ui.label("One block per kind — referenced by jobs and on-demand requests.").classes("ink-small")

        for preset in presets:
            _render_preset_row(api, preset, blocks_by_kind, reload)

        with (
            ui.element("div").classes("bento-tile w-full").style("padding: 16px;"),
            ui.column().classes("w-full gap-2"),
        ):
            ui.label("Add new preset").classes("ink-eyebrow")
            name_field = ui.input("Name").classes("w-full").props("outlined")
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


def _render_preset_row(
    api: ApiClient,
    preset: dict[str, Any],
    blocks_by_kind: dict[str, list[dict[str, Any]]],
    reload: Any,
) -> None:
    preset_id = UUID(preset["id"])

    with ui.element("div").classes("bento-tile w-full").style("padding: 16px;"):
        name = ui.input(value=preset["name"], label="Name").classes("w-full").props("outlined dense")
        selectors: dict[str, Any] = {}
        with ui.column().classes("w-full gap-2"):
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


async def tile() -> None:
    """Render the prompts landing tile."""
    api = require_api_client()
    try:
        blocks = await api.list_prompt_blocks()
        presets = await api.list_prompt_presets()
    except ApiError:
        logger.exception("list_prompt_blocks failed on landing tile")
        blocks, presets = [], []

    with bento_tile(span="col-span-4", href="/prompts"):
        stat(label="AI prompts", value=f"{len(presets)}", hint=f"{len(blocks)} blocks")


__all__ = ["register", "tile"]
