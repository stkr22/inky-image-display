"""Display view: stacked Devices / Grids / Schedule sections under one route."""

from __future__ import annotations

from nicegui import ui

from inky_image_display_ui.views import devices, grids, schedule
from inky_image_display_ui.views._layout import frame


def register() -> None:
    """Register the unified display route plus the grid-detail deep-link."""
    grids.register()

    @ui.page("/displays")
    async def display_page() -> None:
        with frame("/displays"):
            await schedule.render_section()
            ui.element("div").style("height: 32px;")
            await devices.render_section()
            ui.element("div").style("height: 32px;")
            await grids.render_section()


async def tile() -> None:
    """Reuse the devices wall tile as the Display landing summary."""
    await devices.tile()
