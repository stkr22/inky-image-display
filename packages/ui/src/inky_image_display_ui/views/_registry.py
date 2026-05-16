"""Central page registry.

Each view module exposes a ``register()`` callable that wires its ``@ui.page``
routes and (optionally) a ``tile()`` callable that renders its bento card on
the landing page. Adding a new section to the app = one new ``PageSpec``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True)
class PageSpec:
    """Describe one top-level section of the app.

    The ``register`` callable is invoked once at app startup. ``tile`` is
    invoked asynchronously per landing-page render so it can fetch its own
    summary data; views that should not appear on the dashboard leave it
    ``None``.
    """

    path: str
    label: str
    icon: str
    register: Callable[[], None]
    tile: Callable[[], Awaitable[None]] | None = None
    nav_order: int = 100
    show_in_nav: bool = True


def get_pages() -> list[PageSpec]:
    """Return the ordered list of registered pages.

    Imported lazily inside the function so importing this module does not pull
    in every view (and its NiceGUI side effects) at module load time.

    Top-level nav holds four sections: Images, Devices, Jobs, GenAI. The
    per-source job forms and the standalone prompts/generate pages still have
    routes (so deep-links keep working) but are hidden from the nav and
    contribute no landing tiles — their tiles are consolidated into the
    Jobs and GenAI sections.
    """
    from inky_image_display_ui.views import (  # noqa: PLC0415
        devices,
        gemini_jobs,
        genai,
        generate,
        grids,
        images,
        jobs,
        prompts,
        sync_jobs,
    )

    pages: list[PageSpec] = [
        PageSpec(
            path="/images",
            label="Images",
            icon="image",
            register=images.register,
            tile=images.tile,
            nav_order=10,
        ),
        PageSpec(
            path="/devices",
            label="Devices",
            icon="devices",
            register=devices.register,
            tile=devices.tile,
            nav_order=20,
        ),
        PageSpec(
            path="/grids",
            label="Grids",
            icon="grid_view",
            register=grids.register,
            tile=None,
            nav_order=25,
        ),
        PageSpec(
            path="/jobs",
            label="Jobs",
            icon="sync",
            register=jobs.register,
            tile=jobs.tile,
            nav_order=30,
        ),
        PageSpec(
            path="/genai",
            label="GenAI",
            icon="auto_awesome",
            register=genai.register,
            tile=None,
            nav_order=40,
        ),
        # Hidden from nav: per-source job forms and legacy standalone pages.
        # Routes are still registered so deep links and edit URLs work.
        PageSpec(
            path="/sync-jobs",
            label="Immich jobs",
            icon="sync",
            register=sync_jobs.register,
            tile=None,
            nav_order=100,
            show_in_nav=False,
        ),
        PageSpec(
            path="/gemini-jobs",
            label="Gemini jobs",
            icon="bolt",
            register=gemini_jobs.register,
            tile=None,
            nav_order=101,
            show_in_nav=False,
        ),
        PageSpec(
            path="/generate",
            label="Generate",
            icon="auto_awesome",
            register=generate.register,
            tile=None,
            nav_order=102,
            show_in_nav=False,
        ),
        PageSpec(
            path="/prompts",
            label="Prompts",
            icon="article",
            register=prompts.register,
            tile=None,
            nav_order=103,
            show_in_nav=False,
        ),
    ]
    return sorted(pages, key=lambda p: p.nav_order)
