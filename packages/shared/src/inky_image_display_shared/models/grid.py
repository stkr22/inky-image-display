"""Grid display target models.

A grid groups multiple devices into a virtual canvas that displays slices of
a single source image. Devices are placed on the canvas in physical cm
coordinates; the API pre-renders per-device crops so controllers receive an
ordinary display command pointing at their slice.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class Grid(SQLModel, table=True):
    """A virtual canvas spanning a group of devices.

    A grid does not rotate on an interval: it shows one queue entry per
    scheduled daily display (or operator action), holds it, and then hands
    the member panels back to their own solo rotation.
    """

    __tablename__ = "grids"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    width_cm: float
    height_cm: float
    current_image_id: UUID | None = Field(default=None, foreign_key="images.id")
    displayed_since: datetime | None = Field(default=None)

    # Display schedule: when this grid steps its content queue one entry
    # forward. Same cron mechanism as the jobs: ``display_cron`` is a
    # five-field expression evaluated as wall-clock time in
    # ``display_timezone`` — the repo is otherwise UTC-everywhere, but a
    # "show at 08:00" schedule only makes sense in the operator's local
    # time. The enabled flag toggles the schedule without losing it.
    display_schedule_enabled: bool = Field(default=False)
    display_cron: str = Field(default="0 8 * * *")
    display_timezone: str = Field(default="UTC")
    # ``None`` shows the content until the operator releases it manually.
    display_duration_seconds: int | None = Field(default=None)

    # Queue playback state: the group currently on the panels.
    # ``current_group_id`` is intentionally not a FK: image_groups
    # references grids, and a back-reference would create a circular FK
    # that complicates table creation order.
    current_group_id: UUID | None = Field(default=None)
    # When the current display ends and the panels are released. The
    # scheduled daily display and manual "show now" set it; expiry or an
    # explicit release clears it.
    hold_until: datetime | None = Field(default=None)
    # Next scheduled display as naive UTC — the same lease pattern as the
    # jobs' ``next_run_at``: stamped when the schedule is enabled/edited,
    # advanced along the cron grid when a display fires. ``None`` while
    # the schedule is disabled.
    display_next_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})


class GridDevice(SQLModel, table=True):
    """A device's placement on a grid canvas.

    Placements are computed from a tile layout: ``row``/``col`` are the
    device's slot in that layout (row 0 = top). Slots are the stable,
    user-facing address for a panel — display jobs map content onto slots.
    The cm-rect is still persisted explicitly so crops don't need to
    recompute geometry on every render and so later profile-dim corrections
    do not silently shift existing placements.
    """

    __tablename__ = "grid_devices"

    grid_id: UUID = Field(foreign_key="grids.id", primary_key=True, ondelete="CASCADE")
    device_id: UUID = Field(foreign_key="devices.id", primary_key=True, ondelete="CASCADE")
    row: int = Field(default=0, description="Layout row (0 = top)")
    col: int = Field(default=0, description="Position within the row (0 = left)")
    top_left_x_cm: float
    top_left_y_cm: float
    width_cm: float
    height_cm: float
    created_at: datetime = Field(default_factory=utcnow)
