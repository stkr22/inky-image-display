"""Device display state model for Inky displays."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


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
    scheduled_next_at: datetime = Field(default_factory=datetime.now, description="Scheduled time for next image")


class Device(SQLModel, table=True):
    """API-managed device record.

    Replaces the combination of GlobalDevice + DeviceDisplayState for the API
    service. The skill continues to use DeviceDisplayState + GlobalDevice
    unchanged.

    Attributes:
        id: Unique identifier
        device_id: String device identifier (e.g. 'inky-kitchen')
        room: Room where device is located
        display_width: Display width in pixels
        display_height: Display height in pixels
        display_orientation: Display orientation
        display_model: Display hardware model
        is_online: Whether device is currently connected
        current_image_id: Currently displayed image
        displayed_since: When current image was displayed
        scheduled_next_at: When to show next image
        created_at: When record was created
        updated_at: When record was last updated

    """

    __tablename__ = "devices"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    device_id: str = Field(unique=True, index=True, description="Device string identifier, e.g. 'inky-kitchen'")
    room: str | None = Field(default=None)
    display_width: int = Field(default=1600)
    display_height: int = Field(default=1200)
    display_orientation: str = Field(default="landscape")
    display_model: str = Field(default="inky_impression_13_spectra6")
    is_online: bool = Field(default=False)
    current_image_id: UUID | None = Field(default=None, foreign_key="images.id")
    displayed_since: datetime | None = Field(default=None)
    scheduled_next_at: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
