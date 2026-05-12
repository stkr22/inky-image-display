"""Shared page chrome: sticky top nav + page container.

Replaces the previous Quasar header/drawer with a custom, light-minimal top
bar built from real ``<a href>`` anchors so clicks navigate client-side
without a websocket round-trip.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from nicegui import ui

from inky_image_display_ui.views._registry import PageSpec, get_pages
from inky_image_display_ui.views._ui import install_global_styles

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def frame(active_path: str) -> Iterator[ui.column]:
    """Render top nav + content container; yield a column for the page body."""
    install_global_styles()
    _render_top_nav(active_path)

    body = ui.column().classes("ink-page")
    with body:
        yield body


def _render_top_nav(active_path: str) -> None:
    pages = [p for p in get_pages() if p.show_in_nav]
    drawer = _build_mobile_sheet(pages, active_path)

    with ui.element("div").classes("ink-nav"):
        with ui.link(target="/").classes("ink-nav-brand"):
            ui.html('<span class="ink-nav-brand-dot"></span>')
            ui.label("Inky").classes("text-base")
            ui.label("/ image display").classes("text-base ink-muted")

        ui.element("div").classes("flex-1")

        with ui.element("nav").classes("ink-nav-links"):
            for page in pages:
                _nav_link(page.path, page.label, active=page.path == active_path)

        with (
            ui.element("button")
            .classes("ink-btn ink-btn-ghost ink-btn-icon ink-nav-mobile-toggle")
            .on("click", drawer.open)
        ):
            ui.icon("menu")


def _nav_link(path: str, label: str, *, active: bool) -> None:
    classes = "ink-nav-link is-active" if active else "ink-nav-link"
    with ui.link(target=path).classes(classes):
        ui.label(label)


def _build_mobile_sheet(pages: list[PageSpec], active_path: str) -> ui.dialog:
    dialog = ui.dialog().props("position=right")
    with (
        dialog,
        ui.card()
        .classes("w-[280px] h-screen rounded-none")
        .style("background: var(--ink-surface); border-left: 1px solid var(--ink-border);"),
    ):
        with ui.row().classes("w-full items-center justify-between p-4"):
            ui.label("Menu").classes("ink-eyebrow")
            ui.button(icon="close", on_click=dialog.close).props("flat round")
        with ui.column().classes("w-full gap-1 px-2 pb-4"):
            for page in pages:
                cls = "ink-nav-link is-active" if page.path == active_path else "ink-nav-link"
                with (
                    ui.link(target=page.path)
                    .classes(f"{cls} w-full")
                    .style("display: flex; gap: 10px; padding: 12px 14px;")
                ):
                    ui.icon(page.icon)
                    ui.label(page.label)
    return dialog
