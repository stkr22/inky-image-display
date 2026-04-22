"""Pydantic request / response schemas for the REST API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# --- Images ---


class ImageCreate(BaseModel):
    """Metadata supplied when uploading an image (multipart form).

    When ``is_portrait`` is omitted, the upload handler derives it from the
    actual pixel shape of the file. Provide it explicitly to mark an image
    as intended for a portrait-oriented device regardless of raster shape.
    """

    source_name: str = "manual"
    title: str | None = None
    description: str | None = None
    author: str | None = None
    display_duration_seconds: int = 600
    priority: int = 5
    tags: str | None = None
    is_portrait: bool | None = None


class ImageRegister(BaseModel):
    """Register an image that was pre-uploaded directly to S3."""

    source_name: str = "immich"
    source_id: str | None = None
    sync_job_name: str | None = None
    storage_path: str
    source_url: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    tags: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    is_portrait: bool = False
    display_duration_seconds: int = 600
    priority: int = 5
    expires_at: datetime | None = None


class ImageUpdate(BaseModel):
    """Fields accepted when updating image metadata (all optional)."""

    source_name: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    tags: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    is_portrait: bool | None = None
    display_duration_seconds: int | None = None
    priority: int | None = None
    expires_at: datetime | None = None


class ImageResponse(BaseModel):
    """Image data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_name: str
    source_id: str | None
    sync_job_name: str | None
    storage_path: str
    source_url: str | None
    title: str | None
    description: str | None
    author: str | None
    original_width: int | None
    original_height: int | None
    is_portrait: bool
    display_duration_seconds: int
    priority: int
    last_displayed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    tags: str | None


# --- Devices ---


class DeviceResponse(BaseModel):
    """Device data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    room: str | None
    display_width: int
    display_height: int
    display_orientation: str
    display_model: str
    is_online: bool
    current_image_id: UUID | None
    displayed_since: datetime | None
    scheduled_next_at: datetime


class DisplayCommandRequest(BaseModel):
    """Request body for sending a specific image to a device."""

    image_id: UUID


class NextImageResponse(BaseModel):
    """Response returned after triggering FIFO image selection on a device."""

    status: str
    image_id: UUID
    title: str | None
    description: str | None
    source_name: str
    author: str | None


# --- Sync Jobs ---


class SyncJobCreate(BaseModel):
    """Fields accepted when creating a sync job."""

    name: str
    is_active: bool = True
    target_device_id: UUID
    strategy: str = "RANDOM"
    query: str | None = None
    count: int = 10
    random_pick: bool = False
    overfetch_multiplier: int = 3
    album_ids: list[str] | None = None
    person_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    is_favorite: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    taken_after: datetime | None = None
    taken_before: datetime | None = None
    rating: int | None = None
    min_color_score: float = 0.5
    min_vibrancy_score: float = 0.2


class SyncJobUpdate(BaseModel):
    """Fields accepted when updating a sync job (all optional)."""

    name: str | None = None
    is_active: bool | None = None
    target_device_id: UUID | None = None
    strategy: str | None = None
    query: str | None = None
    count: int | None = None
    random_pick: bool | None = None
    overfetch_multiplier: int | None = None
    album_ids: list[str] | None = None
    person_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    is_favorite: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    taken_after: datetime | None = None
    taken_before: datetime | None = None
    rating: int | None = None
    min_color_score: float | None = None
    min_vibrancy_score: float | None = None


class SyncJobResponse(BaseModel):
    """Sync job data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    target_device_id: UUID
    strategy: str
    query: str | None
    count: int
    random_pick: bool
    overfetch_multiplier: int
    album_ids: list[str] | None
    person_ids: list[str] | None
    tag_ids: list[str] | None
    is_favorite: bool | None
    city: str | None
    state: str | None
    country: str | None
    taken_after: datetime | None
    taken_before: datetime | None
    rating: int | None
    min_color_score: float
    min_vibrancy_score: float
    created_at: datetime
    updated_at: datetime
