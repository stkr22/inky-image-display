"""Immich sync job configuration model."""

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class SyncStrategy(enum.StrEnum):
    """Strategy for selecting images from Immich.

    Values are uppercase to match PostgreSQL enum labels created by SQLAlchemy.
    """

    RANDOM = "RANDOM"
    SMART = "SMART"  # CLIP semantic search


class ImmichSyncJob(SQLModel, table=True):
    """Immich sync job configuration stored in database.

    Each job defines a set of filters and selection criteria for syncing
    images from Immich. Jobs can be activated/deactivated and target
    specific devices to determine display requirements.

    Attributes:
        id: Unique job identifier
        name: Human-readable job name (unique)
        is_active: Whether job should be executed during sync
        target_device_profile_id: Profile this job syncs for (determines panel dimensions)
        orientation: Optional per-job orientation override; NULL means any
        strategy: Selection strategy - 'random' or 'smart' (CLIP search)
        query: Semantic search query (required for 'smart' strategy)
        count: Number of images to sync per run
        random_pick: Randomly sample from smart search results
        overfetch_multiplier: Fetch more images to allow for client-side filtering
        album_ids: Filter by album UUIDs
        person_ids: Filter by recognized person UUIDs
        tag_ids: Filter by tag UUIDs
        is_favorite: Filter favorites only
        city: Filter by city name
        state: Filter by state/region
        country: Filter by country
        taken_after: Photos taken after this date
        taken_before: Photos taken before this date
        make: Camera make filter
        camera_model: Camera model filter
        rating: Minimum rating filter (0-5)
        min_color_score: Minimum color compatibility for Spectra 6 (0.0-1.0)
        min_vibrancy_score: Minimum vibrancy (saturation/contrast) for e-ink (0.0-1.0)

    """

    __tablename__ = "immich_sync_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, description="Unique job name")
    is_active: bool = Field(default=True, description="Whether job is active")

    # Target device profile - determines panel size; orientation may override per-job.
    target_device_profile_id: UUID = Field(
        foreign_key="device_profiles.id",
        description="Profile this job syncs for. Panel dimensions come from the profile.",
    )
    orientation: str | None = Field(
        default=None,
        description="Optional orientation override ('landscape' or 'portrait'). NULL = match any.",
    )

    # Selection strategy
    strategy: SyncStrategy = Field(
        default=SyncStrategy.RANDOM,
        description="Selection strategy: 'random' or 'smart' (CLIP semantic search)",
    )
    query: str | None = Field(
        default=None,
        description="Semantic search query for 'smart' strategy",
    )
    count: int = Field(default=10, ge=1, le=1000, description="Images to sync per run")
    random_pick: bool = Field(
        default=False,
        description="Randomly sample from smart search results",
    )
    overfetch_multiplier: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Multiplier for overfetching when client-side filters active",
    )

    # API filters (stored as JSON for list types)
    album_ids: list[str] | None = Field(default=None, sa_column=Column(JSON))
    person_ids: list[str] | None = Field(default=None, sa_column=Column(JSON))
    tag_ids: list[str] | None = Field(default=None, sa_column=Column(JSON))
    is_favorite: bool | None = Field(default=None, description="Filter favorites only")
    city: str | None = Field(default=None, description="Filter by city")
    state: str | None = Field(default=None, description="Filter by state/region")
    country: str | None = Field(default=None, description="Filter by country")
    taken_after: datetime | None = Field(default=None, description="Photos taken after")
    taken_before: datetime | None = Field(default=None, description="Photos taken before")
    rating: int | None = Field(default=None, ge=0, le=5, description="Minimum rating")

    # Client-side filters
    min_color_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum color compatibility score for Spectra 6 palette",
    )
    min_vibrancy_score: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum vibrancy score (saturation or contrast) for e-ink suitability",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now, description="When created")
    updated_at: datetime = Field(default_factory=datetime.now, description="When last updated")
