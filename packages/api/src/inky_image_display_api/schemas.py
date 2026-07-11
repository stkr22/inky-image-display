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
    "GeminiSyncJobCreate",
    "GeminiSyncJobResponse",
    "GeminiSyncJobUpdate",
    "GenerationTaskResponse",
    "GridCreate",
    "GridDeviceAdd",
    "GridDeviceResponse",
    "GridDeviceUpdate",
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
    "MotdAssignmentUpdate",
    "MotdConfigUpdate",
    "MotdDisplayRequest",
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
    max_images: int | None = None
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


# --- Message of the day ---


class MotdAssignmentUpdate(BaseModel):
    """One device's ordered part list inside a config update."""

    device_id: UUID
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


class MotdDisplayRequest(BaseModel):
    """Optional body for ``POST /api/motd/display``.

    ``message_id`` redisplays a specific retained message from the history
    list; omitted (or an empty body) displays the latest ready one.
    """

    message_id: UUID | None = None


class MotdConfigUpdate(BaseModel):
    """Body for ``PUT /api/motd/config``.

    All fields optional so the UI can save one section at a time;
    ``assignments`` replaces the full device list when present.
    """

    content_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    source_mode: Literal["grounded", "knowledge"] | None = None
    image_preset_id: UUID | None = None
    clear_image_preset: bool = False
    text_model_name: str | None = Field(default=None, min_length=1, max_length=100)
    schedule_enabled: bool | None = None
    display_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday_mask: int | None = Field(default=None, ge=1, le=127)
    timezone: str | None = None
    generation_lead_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    display_duration_seconds: RefreshIntervalSeconds | None = None
    # Duration None means "until released"; a dedicated flag distinguishes
    # "leave unchanged" from "set indefinite" in the partial update.
    clear_display_duration: bool = False
    assignments: list[MotdAssignmentUpdate] | None = None

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Unknown IANA timezone: {value}") from exc
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
