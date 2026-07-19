"""Immich sync job configuration model."""

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


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
        max_images: Cap on images this job keeps in the database (0 = unlimited)
        random_pick: Randomly sample from smart search results
        overfetch_multiplier: Fetch more images to allow for client-side filtering
        album_ids: Filter by album UUIDs
        person_ids: Filter by recognized person UUIDs
        tag_ids: Filter by tag UUIDs
        album_match_mode: 'all' = photo must be in every album, 'any' = in at least one
        person_match_mode: 'all' = photo must show every person, 'any' = at least one
        is_favorite: Filter favorites only
        city: Filter by city name
        state: Filter by state/region
        country: Filter by country
        taken_after: Photos taken after this date
        taken_before: Photos taken before this date
        make: Camera make filter
        camera_model: Camera model filter
        rating: Minimum rating filter (0-5)

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
    max_images: int = Field(
        default=10,
        ge=0,
        description="Max images this job keeps in the database; counted against its own uploads (0 = unlimited)",
    )
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
    # Immich's search API intersects multi-value id filters (AND); 'any' makes
    # the sync worker emulate OR by unioning one query per id.
    album_match_mode: str = Field(
        default="all",
        description="How multiple album_ids combine: 'all' (every album) or 'any' (at least one)",
    )
    person_match_mode: str = Field(
        default="all",
        description="How multiple person_ids combine: 'all' (every person) or 'any' (at least one)",
    )
    is_favorite: bool | None = Field(default=None, description="Filter favorites only")
    city: str | None = Field(default=None, description="Filter by city")
    state: str | None = Field(default=None, description="Filter by state/region")
    country: str | None = Field(default=None, description="Filter by country")
    taken_after: datetime | None = Field(default=None, description="Photos taken after")
    taken_before: datetime | None = Field(default=None, description="Photos taken before")
    rating: int | None = Field(default=None, ge=0, le=5, description="Minimum rating")

    # Scheduling lives on the job row so cadence is operator-tunable from
    # the UI instead of baked into deployment cron specs. The worker runs on
    # one frequent cron and claims whatever is due via POST /claim-due.
    # Defaults stay None here (a SQLAlchemy column default would silently
    # override an explicit None at INSERT); the API create schema supplies
    # the default cadence and the route stamps the first next_run_at.
    interval_minutes: int | None = Field(
        default=None,
        ge=1,
        description="Auto-run cadence in minutes; None = manual runs only",
    )
    next_run_at: datetime | None = Field(
        default=None,
        description="When the job is next due; advanced by the claim-due hand-out",
    )
    last_run_at: datetime | None = Field(
        default=None,
        description="Finish time of the most recent reported run",
    )

    # Set by the "Run now" endpoint; makes the job due immediately (active
    # or not) and the run report clears the flag.
    run_requested_at: datetime | None = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=utcnow, description="When created")
    updated_at: datetime = Field(default_factory=utcnow, description="When last updated")
