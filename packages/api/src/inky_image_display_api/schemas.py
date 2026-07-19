"""Pydantic request schemas for the REST API.

Response models live in :mod:`inky_image_display_shared.schemas.responses`
so every consumer (UI service, sync service) validates against the same
wire contract; they are re-exported here for backwards compatibility.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from inky_image_display_shared.motd import is_valid_part
from inky_image_display_shared.schemas.responses import (
    AppSettingsResponse,
    DeviceProfileResponse,
    DeviceResponse,
    GeminiSyncJobResponse,
    GridDeviceResponse,
    GridResponse,
    ImageResponse,
    ImageStatsResponse,
    ImageSummary,
    NextImageResponse,
    PromptBlockResponse,
    PromptPresetResponse,
    QuietHoursSettings,
    ScheduleUpcomingEntry,
    SyncJobResponse,
    SyncJobRunResponse,
    UtcDatetime,
)
from pydantic import BaseModel, Field, field_validator

__all__ = [
    "AppSettingsResponse",
    "AppSettingsUpdate",
    "AuthMeResponse",
    "DeviceProfileResponse",
    "DeviceProfileUpdate",
    "DeviceResponse",
    "DeviceUpdate",
    "DisplayCommandRequest",
    "DisplayJobCreate",
    "DisplayJobDisplayRequest",
    "DisplayJobSlotUpdate",
    "DisplayJobUpdate",
    "GeminiSyncJobCreate",
    "GeminiSyncJobResponse",
    "GeminiSyncJobUpdate",
    "GenerationTaskResponse",
    "GridCreate",
    "GridDeviceResponse",
    "GridDisplayRequest",
    "GridResponse",
    "GridUpdate",
    "GuestInviteResponse",
    "ImageCreate",
    "ImageGenerateRequest",
    "ImageGenerateResponse",
    "ImageRegister",
    "ImageResponse",
    "ImageStatsResponse",
    "ImageSummary",
    "ImageUpdate",
    "ImmichBrowseItem",
    "NextImageResponse",
    "PromptBlockCreate",
    "PromptBlockResponse",
    "PromptBlockUpdate",
    "PromptPresetCreate",
    "PromptPresetResponse",
    "PromptPresetUpdate",
    "QuietHoursSettings",
    "ScheduleUpcomingEntry",
    "SyncJobCreate",
    "SyncJobResponse",
    "SyncJobRunReport",
    "SyncJobRunResponse",
    "SyncJobUpdate",
    "UtcDatetime",
]

# Range guard for refresh interval inputs: 1 second through 1 week.
_MAX_REFRESH_SECONDS = 7 * 24 * 3600
RefreshIntervalSeconds = Annotated[int, Field(ge=1, le=_MAX_REFRESH_SECONDS)]

# Range guard for sync-job cadence: 1 minute through 4 weeks.
SyncIntervalMinutes = Annotated[int, Field(ge=1, le=28 * 24 * 60)]

# --- Images ---


class ImageCreate(BaseModel):
    """Metadata supplied when uploading an image (multipart form).

    ``is_portrait`` may be omitted; the server then derives it from the
    uploaded file's dimensions.
    """

    source_name: str = "manual"
    title: str | None = None
    description: str | None = None
    author: str | None = None
    # None = rotate on the device/global interval. A value pins the image
    # on screen for that long once shown (see image_service scheduling).
    display_duration_seconds: RefreshIntervalSeconds | None = None
    tags: str | None = None
    is_portrait: bool | None = None
    target_grid_id: UUID | None = None


class ImageRegister(BaseModel):
    """Register an image whose bytes were pre-uploaded directly to S3."""

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
    display_duration_seconds: RefreshIntervalSeconds | None = None
    expires_at: datetime | None = None


class ImageUpdate(BaseModel):
    """Patch fields on an existing image (all optional).

    ``display_duration_seconds`` uses ``exclude_unset`` semantics like every
    other field, so sending an explicit ``null`` clears the per-image hold
    back to the device interval.
    """

    source_name: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    tags: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    is_portrait: bool | None = None
    display_duration_seconds: RefreshIntervalSeconds | None = None
    expires_at: datetime | None = None
    target_grid_id: UUID | None = None
    # Operator veto: True removes the image from all automatic rotation
    # (solo and grid) without deleting it; manual pushes still work.
    excluded_from_rotation: bool | None = None


# --- Devices ---


class DeviceProfileUpdate(BaseModel):
    """Patchable fields on a device profile. Size/model/key are immutable."""

    name: str | None = None


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
    # Pin/unpin: a pinned device keeps its current image until unpinned;
    # manual pushes still work and implicitly leave the image pinned.
    is_pinned: bool | None = None


class DisplayCommandRequest(BaseModel):
    """Request body for sending a specific image to a device.

    ``fit="auto"`` lets the API cover-crop a copy to the panel's exact
    dimensions when they don't match; ``"exact"`` (default) instead
    rejects mismatches with 409 — the controller cannot resize and would
    otherwise ack a failure, flagging a healthy device as stuck.
    """

    image_id: UUID
    fit: Literal["exact", "auto"] = "exact"


# --- Sync Jobs ---


class SyncJobCreate(BaseModel):
    """Fields accepted when creating a sync job."""

    name: str
    is_active: bool = True
    # None = manual runs only (Run-now button); a value auto-runs the job
    # on that cadence via the worker's due-claim polling.
    interval_minutes: SyncIntervalMinutes | None = 60
    target_device_profile_id: UUID
    orientation: str | None = None
    strategy: str = "RANDOM"
    query: str | None = None
    count: int = 10
    max_images: int = 10
    random_pick: bool = False
    overfetch_multiplier: int = 3
    album_ids: list[str] | None = None
    person_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    album_match_mode: Literal["all", "any"] = "all"
    person_match_mode: Literal["all", "any"] = "all"
    is_favorite: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    taken_after: datetime | None = None
    taken_before: datetime | None = None
    rating: int | None = None


class SyncJobUpdate(BaseModel):
    """Fields accepted when updating a sync job (all optional).

    ``interval_minutes`` uses ``exclude_unset`` semantics: sending an
    explicit ``null`` switches the job to manual-only runs.
    """

    name: str | None = None
    is_active: bool | None = None
    interval_minutes: SyncIntervalMinutes | None = None
    target_device_profile_id: UUID | None = None
    orientation: str | None = None
    strategy: str | None = None
    query: str | None = None
    count: int | None = None
    max_images: int | None = None
    random_pick: bool | None = None
    overfetch_multiplier: int | None = None
    album_ids: list[str] | None = None
    person_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    album_match_mode: Literal["all", "any"] | None = None
    person_match_mode: Literal["all", "any"] | None = None
    is_favorite: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    taken_after: datetime | None = None
    taken_before: datetime | None = None
    rating: int | None = None


class SyncJobRunReport(BaseModel):
    """Worker-posted summary of one completed sync job run."""

    job_type: Literal["immich", "gemini"]
    job_id: UUID
    job_name: str
    status: Literal["success", "error"]
    started_at: datetime
    finished_at: datetime
    images_added: int = 0
    images_skipped: int = 0
    images_deleted: int = 0
    detail: str | None = None
    error: str | None = None


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


# --- Gemini sync jobs ---


class GeminiSyncJobCreate(BaseModel):
    """Payload for creating a Gemini batch sync job."""

    name: str
    is_active: bool = True
    # Daily default: Gemini batches spend real generation quota.
    interval_minutes: SyncIntervalMinutes | None = 1440
    target_device_profile_id: UUID
    prompt_preset_id: UUID
    orientation: str = "portrait"
    subjects: list[str] = []
    images_per_subject: int = 1
    retention_days: int | None = None


class GeminiSyncJobUpdate(BaseModel):
    """Patch fields on an existing Gemini sync job (all optional).

    ``interval_minutes``: explicit ``null`` switches to manual-only runs.
    """

    name: str | None = None
    is_active: bool | None = None
    interval_minutes: SyncIntervalMinutes | None = None
    target_device_profile_id: UUID | None = None
    prompt_preset_id: UUID | None = None
    orientation: str | None = None
    subjects: list[str] | None = None
    images_per_subject: int | None = None
    retention_days: int | None = None


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


class GenerationTaskResponse(BaseModel):
    """Status snapshot of one on-demand generation task.

    Backed by the in-process task registry, so history covers the current
    API process lifetime — enough to answer "did my generation work?".
    """

    task_id: UUID
    subject: str
    status: str
    created_at: UtcDatetime
    finished_at: UtcDatetime | None
    image_id: UUID | None
    error: str | None
    detail: str | None


# --- Immich browsing (proxy) ---


class ImmichBrowseItem(BaseModel):
    """A selectable Immich entity (album, person or tag) for job filters."""

    id: str
    name: str


# --- Grids ---


def _validate_layout_rows(rows: list[list[UUID]]) -> list[list[UUID]]:
    if any(len(row) == 0 for row in rows):
        raise ValueError("Layout rows must not be empty")
    return rows


def _validate_timezone(value: str | None) -> str | None:
    if value is not None:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


class GridCreate(BaseModel):
    """Payload to create a grid.

    ``rows`` is the visual tile arrangement (rows top-down, devices
    left-to-right); every cm value — canvas size and placements — is
    computed server-side from the device profiles' physical dimensions.
    The display schedule starts disabled; the UI edits it via update.
    """

    name: str
    rows: list[list[UUID]] = Field(min_length=1)
    refresh_interval_seconds: RefreshIntervalSeconds | None = None

    _rows_not_empty = field_validator("rows")(_validate_layout_rows)


class GridUpdate(BaseModel):
    """Patch fields on an existing grid (all optional).

    ``rows`` replaces the whole layout; placements and canvas size are
    recomputed from device profiles. The ``display_*`` fields schedule when
    the grid shows generated display-job content.
    """

    name: str | None = None
    rows: list[list[UUID]] | None = Field(default=None, min_length=1)
    refresh_interval_seconds: RefreshIntervalSeconds | None = None
    clear_refresh_interval: bool = False
    display_schedule_enabled: bool | None = None
    display_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    display_weekday_mask: int | None = Field(default=None, ge=1, le=127)
    display_timezone: str | None = None
    display_duration_seconds: RefreshIntervalSeconds | None = None
    # Duration None means "until released"; a dedicated flag distinguishes
    # "leave unchanged" from "set indefinite" in the partial update.
    clear_display_duration: bool = False

    _valid_timezone = field_validator("display_timezone")(_validate_timezone)

    @field_validator("rows")
    @classmethod
    def _rows_not_empty(cls, value: list[list[UUID]] | None) -> list[list[UUID]] | None:
        if value is not None:
            _validate_layout_rows(value)
        return value


class GridDisplayRequest(BaseModel):
    """Body for ``POST /api/grids/{id}/display``."""

    image_id: UUID


# --- App settings ---


class AppSettingsUpdate(BaseModel):
    """Body for ``PUT /api/app-settings``.

    Both sections are optional so the UI can save one card at a time
    without re-submitting (and re-validating) the other.
    """

    default_refresh_seconds: RefreshIntervalSeconds | None = None
    quiet_hours: QuietHoursSettings | None = None


# --- Display jobs ---


class DisplayJobSlotUpdate(BaseModel):
    """One grid slot's ordered part list inside a job update."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    parts: list[str] = Field(min_length=1)

    @field_validator("parts")
    @classmethod
    def _valid_parts(cls, value: list[str]) -> list[str]:
        invalid = [part for part in value if not is_valid_part(part)]
        if invalid:
            raise ValueError(f"Unknown content parts: {', '.join(invalid)}")
        if len(set(value)) != len(value):
            raise ValueError("Content parts must not repeat")
        return value


class DisplayJobCreate(BaseModel):
    """Body for ``POST /api/display-jobs``.

    Content fields start on the model defaults; the UI edits them
    afterwards via the update endpoint. ``interval_minutes`` ``None`` means
    manual generation only, matching the sync jobs.
    """

    name: str = Field(min_length=1, max_length=200)
    job_type: Literal["motd"] = "motd"
    target_grid_id: UUID | None = None
    interval_minutes: SyncIntervalMinutes | None = None


class DisplayJobDisplayRequest(BaseModel):
    """Optional body for ``POST /api/display-jobs/{id}/display``.

    ``message_id`` redisplays a specific retained message from the history
    list; omitted (or an empty body) displays the latest ready one.
    """

    message_id: UUID | None = None


class DisplayJobUpdate(BaseModel):
    """Body for ``PUT /api/display-jobs/{id}``.

    All fields optional so the UI can save one section at a time;
    ``slots`` replaces the full slot mapping when present.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_grid_id: UUID | None = None
    clear_target_grid: bool = False
    content_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    source_mode: Literal["grounded", "knowledge"] | None = None
    image_preset_id: UUID | None = None
    clear_image_preset: bool = False
    text_model_name: str | None = Field(default=None, min_length=1, max_length=100)
    interval_minutes: SyncIntervalMinutes | None = None
    # Interval None means "manual generation only"; a dedicated flag
    # distinguishes "leave unchanged" from "set manual" in the partial update.
    clear_interval: bool = False
    slots: list[DisplayJobSlotUpdate] | None = None

    @field_validator("slots")
    @classmethod
    def _unique_slots(cls, value: list[DisplayJobSlotUpdate] | None) -> list[DisplayJobSlotUpdate] | None:
        if value is not None:
            keys = [(slot.row, slot.col) for slot in value]
            if len(set(keys)) != len(keys):
                raise ValueError("Each grid slot can be mapped only once")
        return value


class AuthMeResponse(BaseModel):
    """Session info for the SPA: drives the sign-in gate and guest UI.

    ``role`` is the *effective* role — anonymous requests report ``admin``
    while auth is disabled (trusted-LAN mode) and ``None`` once it is
    enforced, so the frontend needs no separate mode probing.
    """

    auth_enabled: bool
    authenticated: bool
    role: Literal["admin", "guest"] | None
    name: str | None = None


class GuestInviteResponse(BaseModel):
    """A freshly minted guest invite link with its QR rendering inlined.

    The QR ships as base64 PNG in the JSON body instead of a separate image
    endpoint so no extra authenticated URL surface is needed for <img> tags.
    """

    url: str
    expires_at: UtcDatetime
    qr_png_base64: str
