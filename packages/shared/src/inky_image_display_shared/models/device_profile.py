"""Device profile model — the fixed lineup of supported display panels.

Devices reference a profile by FK and inherit panel dimensions and model
identifier from it, so the controller no longer needs to send raw specs
at registration.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class DeviceProfile(SQLModel, table=True):
    """A supported Inky display panel."""

    __tablename__ = "device_profiles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    key: str = Field(unique=True, index=True, description="Stable lookup slug, e.g. 'inky_impression_13_spectra6'")
    name: str = Field(description="Human label, e.g. 'Inky Impression 13.3\" Spectra 6'")
    # width is stored as the longer (landscape-native) side; the orientation
    # lives on the Device row and callers swap dims when needed.
    width: int
    height: int
    # Physical active-area dimensions (cm) from Pimoroni's published specs.
    # Used by the grid feature to project a placed device onto a virtual
    # wall canvas; the longer side is stored as the width to match the
    # landscape-native convention for pixel dims.
    physical_width_cm: float = Field(default=0.0)
    physical_height_cm: float = Field(default=0.0)
    model: str = Field(description="Hardware identifier reported by inky.auto")
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})
