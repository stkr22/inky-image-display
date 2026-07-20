"""Grid display target models.

A grid groups multiple devices into a virtual canvas that displays slices of
a single source image. Devices are placed on the canvas in physical cm
coordinates; the API pre-renders per-device crops so controllers receive an
ordinary display command pointing at their slice.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class Grid(SQLModel, table=True):
    """A virtual canvas spanning a group of devices.

    Mirrors the per-device rotation-state fields so the same background
    rotation pattern can drive grids and individual devices.
    """

    __tablename__ = "grids"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    width_cm: float
    height_cm: float
    current_image_id: UUID | None = Field(default=None, foreign_key="images.id")
    displayed_since: datetime | None = Field(default=None)
    scheduled_next_at: datetime = Field(default_factory=utcnow)
    # Per-grid rotation cadence. ``None`` falls back to
    # ``settings.default_display_duration`` (matches Device behaviour);
    # previously cadence was implicitly driven by ``image.display_duration_seconds``.
    refresh_interval_seconds: int | None = Field(default=None)

    # Daily display schedule: when this grid front-runs its queue with the
    # newest generated group from the display jobs targeting it.
    # ``display_time`` is a local wall-clock "HH:MM" in ``display_timezone``
    # — the repo is otherwise UTC-everywhere, but a "show at 08:00" schedule
    # only makes sense in the operator's local time. ``display_weekday_mask``
    # bit 0 = Monday.
    display_schedule_enabled: bool = Field(default=False)
    display_time: str = Field(default="08:00")
    display_weekday_mask: int = Field(default=127)
    display_timezone: str = Field(default="UTC")
    # ``None`` shows the content until the operator releases it manually.
    display_duration_seconds: int | None = Field(default=None)

    # Queue playback state: the group currently on the panels and which of
    # its frames is showing. ``current_group_id`` is intentionally not a FK:
    # image_groups references grids, and a back-reference would create a
    # circular FK that complicates table creation order.
    current_group_id: UUID | None = Field(default=None)
    current_frame: int = Field(default=0)
    # While set and in the future, the queue does not advance past the
    # current group (frames still rotate). The scheduled daily display and
    # manual "show now" set it; release clears it.
    hold_until: datetime | None = Field(default=None)
    # Once-per-day guard for the scheduler tick, a local date in
    # ``display_timezone`` so "today" matches the operator's calendar.
    last_displayed_on: date | None = Field(default=None)

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
