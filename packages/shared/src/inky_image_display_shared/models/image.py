"""Image model for storing picture metadata."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class Image(SQLModel, table=True):
    """Image metadata stored in the database.

    Images are fetched from various sources (manual upload, Immich, Unsplash, etc.)
    and stored in MinIO. This table tracks metadata for display scheduling and
    voice command responses.

    Attributes:
        id: Unique identifier for the image
        source_name: Source type (e.g., "manual", "immich", "unsplash")
        source_id: Stable identifier at the source (e.g. Immich asset UUID)
        sync_job_name: Name of the sync job that created this record, if any
        storage_path: Path to image in MinIO bucket
        title: Optional title for voice responses
        description: Optional description for "what am I seeing?" queries
        author: Optional author/photographer name
        source_url: Optional HTTPS URL back to the original asset on its source
        display_duration_seconds: Optional per-image hold time; None uses the
            device/global refresh interval
        priority: Legacy weight, never consulted by selection; kept only so
            old rows load
        original_width: Image width in pixels
        original_height: Image height in pixels
        last_displayed_at: When the image was last shown (for FIFO selection)
        expires_at: Optional expiration time for auto-cleanup
        created_at: When record was created (replaces fetched_at)
        updated_at: When record was last updated
        tags: Comma-separated tags for categorization

    """

    __tablename__ = "images"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_name: str = Field(index=True, description="Source type (e.g. manual, immich, unsplash)")
    source_id: str | None = Field(
        default=None,
        index=True,
        description="Stable identifier at the source (e.g. Immich asset UUID)",
    )
    sync_job_name: str | None = Field(
        default=None,
        description="Name of the sync job that created this record, if any",
    )
    storage_path: str = Field(description="MinIO object path")

    # Metadata for voice responses
    title: str | None = Field(default=None, description="Image title for voice responses")
    description: str | None = Field(default=None, description="Description for 'what am I seeing?'")
    author: str | None = Field(default=None, description="Author/photographer name")
    source_url: str | None = Field(default=None, description="HTTPS URL to the original asset")

    # Display settings. ``display_duration_seconds`` overrides the device's
    # rotation interval while this image is up; NULL (the default) defers to
    # the device/global interval. Historic rows carried a dead 600s default
    # that never influenced scheduling — migration 0017 nulls them out so
    # wiring the override up doesn't retroactively speed every device to 10
    # minutes.
    display_duration_seconds: int | None = Field(default=None, description="Optional per-image hold time in seconds")
    priority: int = Field(default=5, description="Legacy, unused by selection; kept so old rows load")

    # Operator veto: excluded images never enter automatic rotation but can
    # still be pushed manually. Cheaper than deletion when the objection is
    # "not on my wall", not "remove from the library".
    excluded_from_rotation: bool = Field(default=False, index=True)

    # Image dimensions and orientation for device compatibility
    original_width: int | None = Field(default=None, description="Image width in pixels")
    original_height: int | None = Field(default=None, description="Image height in pixels")
    is_portrait: bool = Field(default=False, description="True if image is portrait-oriented (height > width)")

    # When set, this image is a member of the grid's image pool and is
    # excluded from solo per-device rotation.
    target_grid_id: UUID | None = Field(
        default=None,
        foreign_key="grids.id",
        ondelete="SET NULL",
        index=True,
    )

    # Timestamps
    last_displayed_at: datetime | None = Field(default=None, description="Last display time for FIFO")
    expires_at: datetime | None = Field(default=None, description="Expiration time for cleanup")
    created_at: datetime = Field(default_factory=utcnow, description="When record was created")
    updated_at: datetime = Field(default_factory=utcnow, description="When record was last updated")

    # Categorization
    tags: str | None = Field(default=None, description="Comma-separated tags for categorization")
