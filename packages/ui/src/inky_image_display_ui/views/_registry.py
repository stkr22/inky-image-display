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
    """
    from inky_image_display_ui.views import devices, images, sync_jobs  # noqa: PLC0415

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
            path="/sync-jobs",
            label="Sync jobs",
            icon="sync",
            register=sync_jobs.register,
            tile=sync_jobs.tile,
            nav_order=30,
        ),
    ]
    return sorted(pages, key=lambda p: p.nav_order)
