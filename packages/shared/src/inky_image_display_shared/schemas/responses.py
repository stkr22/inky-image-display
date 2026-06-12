"""Response schemas of the REST API, shared across services.

These are the wire contracts every consumer (UI service, sync service,
future clients) reads. They live in the shared package so consumers can
validate payloads against the same definitions the API serializes with,
instead of re-deriving shapes from ``dict[str, Any]`` access patterns.

Request/update schemas remain in ``inky_image_display_api.schemas`` —
only the API accepts input, so there is nothing to share on that side.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer

from inky_image_display_shared.time import as_utc_aware

# Stored datetimes are naive UTC by convention (see
# ``inky_image_display_shared.time``). At the API boundary we attach
# ``tzinfo=UTC`` so clients get unambiguous offset-aware ISO strings
# (e.g. ``2026-05-17T14:00:00+00:00``).
UtcDatetime = Annotated[datetime, PlainSerializer(lambda v: as_utc_aware(v).isoformat(), return_type=str)]


# --- Images ---


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


class ImageStatsResponse(BaseModel):
    """Aggregate image counts for dashboard tiles.

    Computed server-side with COUNT/GROUP BY so dashboards don't have to
    page through full image rows just to show totals.
    """

    total: int
    by_source: dict[str, int]


class ImageSummary(BaseModel):
    """Minimal image reference embedded in other responses.

    Carries just enough for a thumbnail + caption so list endpoints can
    include the current image without forcing per-row follow-up requests.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    storage_path: str
    title: str | None


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
    # Populated by the device routes from current_image_id in one batched
    # query, so list consumers don't issue a follow-up request per device.
    current_image: ImageSummary | None = None


class NextImageResponse(BaseModel):
    """Result of a FIFO next-image push."""

    status: str
    image_id: UUID
    title: str | None
    description: str | None
    source_name: str
    author: str | None


# --- Sync jobs (Immich) ---


class SyncJobResponse(BaseModel):
    """Immich sync job data returned by the API."""

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


# --- Prompt blocks / presets ---


class PromptBlockResponse(BaseModel):
    """Prompt block data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    name: str
    text: str
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class PromptPresetResponse(BaseModel):
    """Prompt preset data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    style_block_id: UUID
    palette_block_id: UUID
    legibility_block_id: UUID
    composition_block_id: UUID
    background_block_id: UUID
    model_name: str = "gemini-2.5-flash-image"
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


# --- Gemini sync jobs ---


class GeminiSyncJobResponse(BaseModel):
    """Gemini batch job data returned by the API."""

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


# --- Grids ---


class GridDeviceResponse(BaseModel):
    """A device placement on a grid (bottom-left corner, Y-up)."""

    model_config = ConfigDict(from_attributes=True)

    grid_id: UUID
    device_id: UUID
    bottom_left_x_cm: float
    bottom_left_y_cm: float
    width_cm: float
    height_cm: float


class GridResponse(BaseModel):
    """Grid data returned by the API, optionally with placements."""

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


# --- Schedule ---


class ScheduleUpcomingEntry(BaseModel):
    """One row in the merged upcoming-refresh queue (device or grid)."""

    kind: str
    id: UUID
    name: str
    scheduled_next_at: UtcDatetime
    refresh_interval_seconds: int | None
    effective_interval_seconds: int


# --- App settings ---


class AppSettingsResponse(BaseModel):
    """Operator-tunable app settings."""

    default_refresh_seconds: int
