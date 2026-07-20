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
    group_id: UUID | None = None
    group_slot_row: int | None = None
    group_slot_col: int | None = None
    queue_position: int = 0


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
    album_match_mode: str = "all"
    person_match_mode: str = "all"
    is_favorite: bool | None
    city: str | None
    state: str | None
    country: str | None
    taken_after: datetime | None
    taken_before: datetime | None
    rating: int | None
    interval_minutes: int | None = None
    next_run_at: UtcDatetime | None = None
    last_run_at: UtcDatetime | None = None
    run_requested_at: UtcDatetime | None = None
    created_at: datetime
    updated_at: datetime


class SyncJobRunResponse(BaseModel):
    """One recorded worker run of a job (Immich, Gemini or display).

    ``status`` is ``running`` from claim until the worker's report lands;
    ``finished_at`` is ``None`` for running rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    job_id: UUID
    job_name: str
    status: str
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
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
    interval_minutes: int | None = None
    next_run_at: UtcDatetime | None = None
    last_run_at: UtcDatetime | None = None
    run_requested_at: UtcDatetime | None = None
    created_at: datetime
    updated_at: datetime


# --- Grids ---


class GridDeviceResponse(BaseModel):
    """A device placement on a grid.

    ``row``/``col`` are the layout slot (row 0 = top); the cm rect is the
    computed geometry, expressed as the bottom-left corner Y-up for the
    canvas preview.
    """

    model_config = ConfigDict(from_attributes=True)

    grid_id: UUID
    device_id: UUID
    row: int
    col: int
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
    display_schedule_enabled: bool = False
    display_time: str = "08:00"
    display_weekday_mask: int = 127
    display_timezone: str = "UTC"
    display_duration_seconds: int | None = None
    current_group_id: UUID | None = None
    current_frame: int = 0
    hold_until: UtcDatetime | None = None
    last_displayed_on: date | None = None
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
    grids; manual pushes and display jobs' own explicit schedules are not
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


# --- Display jobs ---


class DisplayJobSlotResponse(BaseModel):
    """One grid slot's part mapping within a display job."""

    row: int
    col: int
    parts: list[str]


class DisplayJobResponse(BaseModel):
    """A display job's configuration and worker schedule state."""

    id: UUID
    name: str
    job_type: str
    target_grid_id: UUID | None
    content_prompt: str
    # Shipped default so the UI can offer "reset to default" without
    # hardcoding a copy of the prompt.
    default_prompt: str
    source_mode: str
    image_preset_id: UUID | None
    text_model_name: str
    is_active: bool
    interval_minutes: int | None
    next_run_at: UtcDatetime | None
    last_run_at: UtcDatetime | None
    run_requested_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    slots: list[DisplayJobSlotResponse]


class DisplayJobClaimSlot(BaseModel):
    """A slot with its resolved panel target, handed to the worker at claim."""

    row: int
    col: int
    parts: list[str]
    device_id: str
    width: int
    height: int
    is_portrait: bool


class DisplayJobClaim(BaseModel):
    """One claimed display job with its config and resolved slots.

    No run id is handed out: the claim records a ``running`` run row and
    the worker's posted report completes the newest one for the job.
    """

    id: UUID
    name: str
    target_grid_id: UUID
    content_prompt: str
    source_mode: str
    image_preset_id: UUID | None
    text_model_name: str
    slots: list[DisplayJobClaimSlot]


# --- Image groups / grid queue ---


class ImageGroupResponse(BaseModel):
    """An image group with its member images."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    target_grid_id: UUID | None
    display_job_id: UUID | None
    description: str | None
    source_url: str | None
    queue_position: int
    last_displayed_at: UtcDatetime | None
    created_at: UtcDatetime
    images: list[ImageResponse] = []


class GridQueueEntry(BaseModel):
    """One upcoming entry in a grid's content queue (group or loose image).

    Entries are returned in predicted playback order — the rank *is* the
    list index, so the stored sort key is not exposed.
    """

    kind: str  # "group" | "image"
    id: UUID
    name: str | None
    last_displayed_at: UtcDatetime | None
    # Groups: number of refresh frames the group occupies; images: 1.
    frame_count: int
    # Thumbnail source (a member image for groups, the image itself otherwise).
    storage_path: str | None
    is_current: bool = False


class GridSlotStatus(BaseModel):
    """What one panel of the grid is currently showing."""

    row: int
    col: int
    device_id: str
    is_online: bool
    current_title: str | None


class GridContentStatus(BaseModel):
    """The grid's current queue playback state."""

    group_id: UUID | None
    group_name: str | None
    frame: int
    frame_count: int
    hold_until: UtcDatetime | None
    displayed_since: UtcDatetime | None
    slots: list[GridSlotStatus]


class GroupDisplayResult(BaseModel):
    """Per-device outcome of showing a group on its grid."""

    group_id: UUID
    name: str | None
    displayed: list[str]
    offline: list[str]
    skipped_no_content: list[str]
