"""Device display state model for Inky displays."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class DeviceDisplayState(SQLModel, table=True):
    """Legacy display state for a device.

    Used by the skill package. New services should use the ``Device`` model
    instead.

    Attributes:
        global_device_id: Primary key (UUID, previously FK to global_devices)
        is_online: Whether device is currently reachable
        current_image_id: Currently displayed image (nullable)
        displayed_since: When current image was displayed
        scheduled_next_at: When to show next image

    """

    __tablename__ = "device_display_states"

    global_device_id: UUID = Field(primary_key=True)
    is_online: bool = Field(default=True, description="Whether device is currently reachable")
    current_image_id: UUID | None = Field(default=None, foreign_key="images.id")
    displayed_since: datetime | None = Field(default=None, description="When current image was displayed")
    scheduled_next_at: datetime = Field(default_factory=utcnow, description="Scheduled time for next image")


class Device(SQLModel, table=True):
    """API-managed device record.

    Replaces the combination of GlobalDevice + DeviceDisplayState for the API
    service. The skill continues to use DeviceDisplayState + GlobalDevice
    unchanged.

    Attributes:
        id: Unique identifier
        device_id: String device identifier (e.g. 'inky-kitchen')
        room: Room where device is located
        device_profile_id: FK to the device_profiles row that defines panel size/model
        display_orientation: Per-device orientation ('landscape' or 'portrait')
        is_online: Whether device is currently connected
        current_image_id: Currently displayed image
        displayed_since: When current image was displayed
        scheduled_next_at: When to show next image
        last_seen: Last time the device sent any traffic (registration / ack).
            Drives self-healing online detection so a stale ``is_online``
            flag is corrected on the next message.
        last_refresh_ok: Outcome of the most recent display refresh as reported
            by the device's ack. ``None`` until the first ack is seen, ``True``
            after a successful refresh, ``False`` when the device reported the
            refresh failed (e.g. the e-paper BUSY signal never cleared). Lets
            operators spot a stuck display that is otherwise still "online".
        last_error: Error message from the most recent failed refresh, cleared
            back to ``None`` on the next success.
        last_error_at: When ``last_error`` was recorded.
        created_at: When record was created
        updated_at: When record was last updated

    """

    __tablename__ = "devices"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    device_id: str = Field(unique=True, index=True, description="Device string identifier, e.g. 'inky-kitchen'")
    room: str | None = Field(default=None)
    device_profile_id: UUID = Field(foreign_key="device_profiles.id")
    display_orientation: str = Field(default="landscape")
    is_online: bool = Field(default=False)
    current_image_id: UUID | None = Field(default=None, foreign_key="images.id")
    # Non-null while a grid is actively driving this device. Solo rotation
    # skips claimed devices; only one grid can hold the claim at a time.
    claimed_by_grid_id: UUID | None = Field(default=None, foreign_key="grids.id", ondelete="SET NULL")
    # Non-null while an active message-of-the-day session is driving this
    # device. Mirrors the grid claim; whichever claim exists first wins.
    claimed_by_motd_config_id: UUID | None = Field(default=None, foreign_key="motd_configs.id", ondelete="SET NULL")
    displayed_since: datetime | None = Field(default=None)
    scheduled_next_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    # Display-refresh health, updated from device acks. None = no ack yet.
    last_refresh_ok: bool | None = Field(default=None)
    last_error: str | None = Field(default=None)
    last_error_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    # onupdate ensures any SQLAlchemy UPDATE bumps this — the original
    # default_factory only applied on insert, so updated_at silently
    # froze at row creation time.
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})
    # Per-device rotation cadence. ``None`` falls back to
    # ``settings.default_display_duration`` so existing devices keep their
    # current behaviour without a migration backfill.
    refresh_interval_seconds: int | None = Field(default=None)
