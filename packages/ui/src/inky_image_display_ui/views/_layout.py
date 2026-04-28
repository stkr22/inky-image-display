"""Shared page chrome: header + responsive navigation drawer.

Each view module wraps its content in :func:`frame` so the header, drawer,
and base styling stay consistent across pages.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Iterator

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/images", "Images", "image"),
    ("/devices", "Devices", "devices"),
    ("/sync-jobs", "Sync jobs", "sync"),
]


@contextmanager
def frame(active_path: str) -> Iterator[ui.column]:
    """Render the shared header/drawer and yield a column for the page body.

    The drawer auto-shows on desktop (>= 900px) and is hidden behind a
    hamburger toggle on mobile.
    """
    drawer = ui.left_drawer(value=False, bordered=True).props("breakpoint=900 show-if-above")

    with ui.header().classes("items-center justify-between"), ui.row().classes("items-center gap-2"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat round color=white").classes("md:hidden")
        ui.label("Inky Image Display").classes("text-lg font-medium")

    with drawer, ui.column().classes("w-full gap-1"):
        for path, label, icon in _NAV_ITEMS:
            _nav_link(path=path, label=label, icon=icon, active=path == active_path)

    body = ui.column().classes("w-full max-w-screen-xl mx-auto p-4 gap-4")
    with body:
        yield body


def _nav_link(*, path: str, label: str, icon: str, active: bool) -> None:
    button = ui.button(on_click=lambda p=path: ui.navigate.to(p)).classes("w-full justify-start")
    props = "flat align=left no-caps"
    if active:
        props += " color=primary"
    button.props(props)
    with button:
        ui.icon(icon)
        ui.label(label)
