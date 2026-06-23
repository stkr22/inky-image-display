"""Gemini batch sync job configuration.

Mirrors the role of ``ImmichSyncJob`` for AI-generated images. Each run
generates ``images_per_subject`` images for every entry in ``subjects``,
sized for ``target_device``, using the prompt blocks from ``prompt_preset``.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class GeminiSyncJob(SQLModel, table=True):
    """Recurring AI-generation job: subjects x images_per_subject per run."""

    __tablename__ = "gemini_sync_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, description="Unique job name")
    is_active: bool = Field(default=True)

    target_device_profile_id: UUID = Field(
        foreign_key="device_profiles.id",
        description="Device profile this job generates for; provides target panel dimensions.",
    )
    prompt_preset_id: UUID = Field(
        foreign_key="prompt_presets.id",
        description="Prompt blocks to use when calling Gemini.",
    )
    orientation: str = Field(
        default="portrait",
        description="Orientation for generated images ('landscape' or 'portrait').",
    )

    subjects: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="One Gemini call per subject, multiplied by images_per_subject.",
    )
    images_per_subject: int = Field(default=1, ge=1, le=10)
    retention_days: int | None = Field(
        default=None,
        description="If set, generated images expire after this many days.",
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
