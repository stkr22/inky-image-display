"""Pydantic request / response schemas for the REST API."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from inky_image_display_shared.time import as_utc_aware
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Stored datetimes are naive UTC by convention (see
# ``inky_image_display_shared.time``). At the API boundary we attach
# ``tzinfo=UTC`` so clients get unambiguous offset-aware ISO strings
# (e.g. ``2026-05-17T14:00:00+00:00``).
UtcDatetime = Annotated[datetime, PlainSerializer(lambda v: as_utc_aware(v).isoformat(), return_type=str)]

# Range guard for refresh interval inputs: 1 second through 1 week.
_MAX_REFRESH_SECONDS = 7 * 24 * 3600
RefreshIntervalSeconds = Annotated[int, Field(ge=1, le=_MAX_REFRESH_SECONDS)]

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
    target_grid_id: UUID | None = None


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
    target_grid_id: UUID | None = None


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
    last_displayed_at: UtcDatetime | None
    expires_at: UtcDatetime | None
    created_at: UtcDatetime
    tags: str | None
    target_grid_id: UUID | None = None


# --- Devices ---


class DeviceProfileResponse(BaseModel):
    """Panel profile data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    width: int
    height: int
    physical_width_cm: float
    physical_height_cm: float
    model: str
    is_default: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime


class DeviceProfileUpdate(BaseModel):
    """Patchable fields on a device profile. Size/model/key are immutable."""

    name: str | None = None


class DeviceResponse(BaseModel):
    """Device data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    room: str | None
    device_profile_id: UUID
    display_orientation: str
    is_online: bool
    current_image_id: UUID | None
    claimed_by_grid_id: UUID | None
    displayed_since: UtcDatetime | None
    scheduled_next_at: UtcDatetime
    last_seen: UtcDatetime
    refresh_interval_seconds: int | None = None


class DeviceUpdate(BaseModel):
    """Patch fields on a device (all optional).

    Currently exposes ``refresh_interval_seconds`` so the user can dial
    rotation cadence per device from the UI; ``None`` resets to the
    global default. Other device fields (room, orientation, profile)
    are managed via registration today.
    """

    refresh_interval_seconds: RefreshIntervalSeconds | None = None
    # Explicit flag because pydantic can't distinguish "omitted" from
    # "explicitly null" on a regular ``int | None`` field — the UI uses
    # this to clear the override back to the default.
    clear_refresh_interval: bool = False


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
    target_device_profile_id: UUID
    orientation: str | None = None
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


class SyncJobUpdate(BaseModel):
    """Fields accepted when updating a sync job (all optional)."""

    name: str | None = None
    is_active: bool | None = None
    target_device_profile_id: UUID | None = None
    orientation: str | None = None
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


class SyncJobResponse(BaseModel):
    """Sync job data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    target_device_profile_id: UUID
    orientation: str | None
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
    created_at: datetime
    updated_at: datetime


# --- Prompt blocks & presets ---


class PromptBlockBase(BaseModel):
    """Shared fields for a prompt block (style/palette/legibility/composition/background)."""

    kind: str
    name: str
    text: str
    is_default: bool = False


class PromptBlockCreate(PromptBlockBase):
    """Payload for creating a new prompt block."""


class PromptBlockUpdate(BaseModel):
    """Patch fields on an existing prompt block (all optional)."""

    kind: str | None = None
    name: str | None = None
    text: str | None = None
    is_default: bool | None = None


class PromptBlockResponse(PromptBlockBase):
    """Prompt block data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PromptPresetBase(BaseModel):
    """Shared fields for a prompt preset (one block id per kind)."""

    name: str
    style_block_id: UUID
    palette_block_id: UUID
    legibility_block_id: UUID
    composition_block_id: UUID
    background_block_id: UUID
    model_name: str = "gemini-2.5-flash-image"
    is_default: bool = False


class PromptPresetCreate(PromptPresetBase):
    """Payload for creating a prompt preset."""


class PromptPresetUpdate(BaseModel):
    """Patch fields on an existing prompt preset (all optional)."""

    name: str | None = None
    style_block_id: UUID | None = None
    palette_block_id: UUID | None = None
    legibility_block_id: UUID | None = None
    composition_block_id: UUID | None = None
    background_block_id: UUID | None = None
    model_name: str | None = None
    is_default: bool | None = None


class PromptPresetResponse(PromptPresetBase):
    """Prompt preset data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


# --- Gemini sync jobs ---


class GeminiSyncJobCreate(BaseModel):
    """Payload for creating a Gemini batch sync job."""

    name: str
    is_active: bool = True
    target_device_profile_id: UUID
    prompt_preset_id: UUID
    orientation: str = "portrait"
    subjects: list[str] = []
    images_per_subject: int = 1
    retention_days: int | None = None


class GeminiSyncJobUpdate(BaseModel):
    """Patch fields on an existing Gemini sync job (all optional)."""

    name: str | None = None
    is_active: bool | None = None
    target_device_profile_id: UUID | None = None
    prompt_preset_id: UUID | None = None
    orientation: str | None = None
    subjects: list[str] | None = None
    images_per_subject: int | None = None
    retention_days: int | None = None


class GeminiSyncJobResponse(BaseModel):
    """Gemini sync job data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    target_device_profile_id: UUID
    prompt_preset_id: UUID
    orientation: str
    subjects: list[str]
    images_per_subject: int
    retention_days: int | None
    created_at: datetime
    updated_at: datetime


# --- On-demand AI generation ---


class ImageGenerateRequest(BaseModel):
    """End-user request to generate one image via Gemini and push it.

    ``preset_id`` defaults to the preset marked ``is_default``. Leaving
    ``push_immediately`` enabled means a matching online device will get a
    display command as soon as the image is registered.
    """

    subject: str
    target_device_profile_id: UUID | None = None
    preset_id: UUID | None = None
    orientation: str = "portrait"
    push_immediately: bool = True


class ImageGenerateResponse(BaseModel):
    """Acknowledgement that an image generation has been queued."""

    task_id: UUID
    status: str


# --- Grids ---


class GridCreate(BaseModel):
    """Payload to create a grid."""

    name: str
    width_cm: float
    height_cm: float


class GridUpdate(BaseModel):
    """Patch fields on an existing grid (all optional).

    Resizing a grid re-validates every member device rectangle.
    """

    name: str | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    refresh_interval_seconds: RefreshIntervalSeconds | None = None
    clear_refresh_interval: bool = False


class GridDeviceAdd(BaseModel):
    """Place a device on a grid.

    Coordinates are the device's bottom-left corner on the canvas, with
    the canvas origin at the bottom-left of the grid and Y growing
    upward — the orientation a user reads off a tape measure on a wall.
    """

    device_id: UUID
    bottom_left_x_cm: float
    bottom_left_y_cm: float


class GridDeviceUpdate(BaseModel):
    """Move a placed device on a grid (bottom-left corner, Y-up)."""

    bottom_left_x_cm: float
    bottom_left_y_cm: float


class GridDeviceResponse(BaseModel):
    """A device's placement on a grid (bottom-left corner, Y-up)."""

    model_config = ConfigDict(from_attributes=True)

    grid_id: UUID
    device_id: UUID
    bottom_left_x_cm: float
    bottom_left_y_cm: float
    width_cm: float
    height_cm: float


class GridResponse(BaseModel):
    """Grid data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    width_cm: float
    height_cm: float
    current_image_id: UUID | None
    displayed_since: UtcDatetime | None
    scheduled_next_at: UtcDatetime
    refresh_interval_seconds: int | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    devices: list[GridDeviceResponse] | None = None


class GridDisplayRequest(BaseModel):
    """Body for ``POST /api/grids/{id}/display``."""

    image_id: UUID


# --- Schedule overview ---


class ScheduleUpcomingEntry(BaseModel):
    """One entry in the global upcoming-refresh queue.

    ``kind`` is ``"device"`` or ``"grid"``; ``id`` is the UUID of the
    underlying entity and ``name`` the user-facing label (``device_id``
    string for devices, ``name`` for grids). ``effective_interval_seconds``
    is the resolved cadence — i.e. the per-entity override if set,
    otherwise the global default — so the UI doesn't need to know about
    the fallback.
    """

    kind: str
    id: UUID
    name: str
    scheduled_next_at: UtcDatetime
    refresh_interval_seconds: int | None
    effective_interval_seconds: int
