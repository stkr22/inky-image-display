"""Flet application entry: page setup, routing, and responsive navigation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from inky_image_display_ui.session import configure, get_api_client, require_api_client
from inky_image_display_ui.views import devices, images, sync_jobs

if TYPE_CHECKING:
    from flet.controls.icon_data import IconData

logger = logging.getLogger(__name__)

_MOBILE_BREAKPOINT = 700  # pixel width below which the bottom nav bar is used

__all__ = ["configure", "get_api_client", "main"]


_NAV_ROUTES: list[tuple[str, str, IconData]] = [
    ("/images", "Images", ft.Icons.IMAGE),
    ("/devices", "Devices", ft.Icons.DEVICES),
    ("/sync-jobs", "Sync jobs", ft.Icons.SYNC),
]


def _selected_index_for_route(route: str) -> int:
    """Return the nav index whose route is a prefix of ``route``."""
    for idx, (nav_route, _, _) in enumerate(_NAV_ROUTES):
        if route == nav_route or route.startswith(nav_route + "/"):
            return idx
    return 0


async def main(page: ft.Page) -> None:
    """Flet session entry point.

    Wires up the page theme, routing, and responsive shell, then dispatches
    to the currently selected view.
    """
    api_client = require_api_client()

    page.title = "Inky Image Display"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.session.store.set("api_client", api_client)

    body = ft.Container(expand=True, padding=16)

    async def render() -> None:
        raw = page.route if page.route and page.route != "/" else "/images"
        route = raw.split("?", 1)[0]
        try:
            body.content = await _build_view(page, route)
        except Exception:
            logger.exception("Failed to render view for route %s", route)
            body.content = ft.Text(
                "Something went wrong loading this view. Check the logs.",
                color=ft.Colors.ERROR,
            )
        page.clean()
        page.add(_scaffold(page, body, route))
        page.update()

    async def on_route_change(_event: ft.RouteChangeEvent) -> None:
        await render()

    async def on_resize(_event: object) -> None:
        await render()

    page.on_route_change = on_route_change
    page.on_resize = on_resize

    initial = page.route if page.route and page.route != "/" else "/images"
    page.go(initial)


async def _build_view(page: ft.Page, route: str) -> ft.Control:
    """Dispatch to a view builder based on ``page.route``."""
    if route.startswith("/images"):
        return await images.build(page)
    if route.startswith("/devices"):
        return await devices.build(page)
    if route == "/sync-jobs":
        return await sync_jobs.build_list(page)
    if route == "/sync-jobs/new":
        return await sync_jobs.build_form(page, job_id=None)
    if route.startswith("/sync-jobs/"):
        job_id = route.removeprefix("/sync-jobs/")
        return await sync_jobs.build_form(page, job_id=job_id)
    return ft.Text(f"Unknown route: {route}")


def _scaffold(page: ft.Page, body: ft.Container, route: str) -> ft.Control:
    """Wrap the view body in either a navigation rail or a bottom nav bar."""
    selected = _selected_index_for_route(route)
    width = page.width or 1024

    def _go(index: int) -> None:
        page.go(_NAV_ROUTES[index][0])

    if width >= _MOBILE_BREAKPOINT:
        rail = ft.NavigationRail(
            selected_index=selected,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=80,
            min_extended_width=180,
            destinations=[ft.NavigationRailDestination(icon=icon, label=label) for _, label, icon in _NAV_ROUTES],
            on_change=lambda e: _go(e.control.selected_index),
        )
        return ft.Row(
            [rail, ft.VerticalDivider(width=1), body],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    nav_bar = ft.NavigationBar(
        selected_index=selected,
        destinations=[ft.NavigationBarDestination(icon=icon, label=label) for _, label, icon in _NAV_ROUTES],
        on_change=lambda e: _go(e.control.selected_index),
    )
    return ft.Column([body, nav_bar], expand=True)
