"""Response schemas of the REST API, shared across services.

These are the wire contracts every consumer (UI service, sync service,
future clients) reads. They live in the shared package so consumers can
validate payloads against the same definitions the API serializes with,
instead of re-deriving shapes from ``dict[str, Any]`` access patterns.

Request/update schemas remain in ``inky_image_display_api.schemas`` —
only the API accepts input, so there is nothing to share on that side.
"""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

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
    # None = rotate on the device/global interval; a value holds the image
    # on screen that long. ``priority`` is legacy and never consulted.
    display_duration_seconds: int | None
    priority: int
    excluded_from_rotation: bool = False
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
    # Most recent display-refresh outcome reported by the device. None until
    # the first ack; False flags a stuck/failed refresh on an online device.
    last_refresh_ok: bool | None = None
    last_error: str | None = None
    last_error_at: UtcDatetime | None = None
    # Derived refresh health, computed by the device routes from
    # last_refresh_ok + the failure's age vs the dispatch backoff:
    # None (no ack yet) / "ok" / "failed_retrying" (controller retry loop
    # should self-heal) / "failed_stale" (failure outlived the backoff —
    # likely needs a power cycle). Saves every client re-deriving the
    # backoff arithmetic and keeps the wording consistent.
    refresh_state: str | None = None
    refresh_interval_seconds: int | None = None
    is_pinned: bool = False
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
    max_images: int
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
    run_requested_at: UtcDatetime | None = None
    created_at: datetime
    updated_at: datetime


class SyncJobRunResponse(BaseModel):
    """One recorded worker run of a sync job (Immich or Gemini)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    job_id: UUID
    job_name: str
    status: str
    started_at: UtcDatetime
    finished_at: UtcDatetime
    images_added: int
    images_skipped: int
    images_deleted: int
    detail: str | None
    error: str | None


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
    run_requested_at: UtcDatetime | None = None
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


class QuietHoursSettings(BaseModel):
    """Daily window during which automatic rotation pauses.

    E-paper refreshes flash the panel for ~30 s, which is unwelcome in a
    bedroom at night. During the window the scheduler skips devices and
    grids; manual pushes and the MOTD's own explicit schedule are not
    affected. A window whose start equals its end is treated as disabled.

    Shared between the settings response and the update body so both sides
    validate the time format and timezone identically.
    """

    enabled: bool = False
    start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value


class AppSettingsResponse(BaseModel):
    """Operator-tunable app settings."""

    default_refresh_seconds: int
    quiet_hours: QuietHoursSettings = QuietHoursSettings()


# --- Message of the day ---


class MotdAssignmentResponse(BaseModel):
    """One device's part assignment within the MOTD config."""

    model_config = ConfigDict(from_attributes=True)

    device_id: UUID
    parts: list[str]
    rotation_index: int


class MotdConfigResponse(BaseModel):
    """The MOTD configuration plus live session state."""

    id: UUID
    content_prompt: str
    # Shipped default so the UI can offer "reset to default" without
    # hardcoding a copy of the prompt.
    default_prompt: str
    source_mode: str
    image_preset_id: UUID | None
    text_model_name: str
    schedule_enabled: bool
    display_time: str
    weekday_mask: int
    timezone: str
    generation_lead_minutes: int
    display_duration_seconds: int | None
    active_message_id: UUID | None
    active_since: UtcDatetime | None
    active_expires_at: UtcDatetime | None
    last_generated_on: date | None
    last_displayed_on: date | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    assignments: list[MotdAssignmentResponse]


class MotdScreenResponse(BaseModel):
    """One pre-rendered screen of a generated message."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    part: str
    width: int
    height: int
    is_portrait: bool
    storage_path: str
    created_at: UtcDatetime


class MotdMessageResponse(BaseModel):
    """A generated MOTD story with its rendered screens."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    error: str | None
    headline: str | None
    what: str | None
    why: str | None
    when_text: str | None
    takeaway: str | None
    image_subject: str | None
    source_url: str | None
    source_title: str | None
    source_mode: str
    displayed_at: UtcDatetime | None
    created_at: UtcDatetime
    screens: list[MotdScreenResponse] = []


class MotdDeviceStatus(BaseModel):
    """Live per-device state while a MOTD session is active."""

    device_id: str
    is_online: bool
    current_part: str | None


class MotdStatusResponse(BaseModel):
    """Whether a MOTD session is active and what each device shows."""

    active: bool
    message_id: UUID | None
    headline: str | None
    active_since: UtcDatetime | None
    active_expires_at: UtcDatetime | None
    devices: list[MotdDeviceStatus]


class MotdDisplayResult(BaseModel):
    """Per-device outcome of ``POST /api/motd/display``."""

    message_id: UUID
    headline: str | None
    displayed: list[str]
    offline: list[str]
    skipped_grid_claimed: list[str]
    skipped_no_content: list[str]
