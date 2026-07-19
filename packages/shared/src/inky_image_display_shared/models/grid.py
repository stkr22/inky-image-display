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
