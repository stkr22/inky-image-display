"""Calibre bookshelf job configuration.

Mirrors the role of ``GeminiSyncJob`` for a book library. Each run picks
``images_per_run`` sets of books out of the Calibre catalog — filtered by the
job's criteria, sampled at random — and generates one image per set.

A job runs exactly one ``mode``. Splitting them keeps the row honest: a shelf
needs several books and a landscape panel, a bookcase stacks several shelves on
a portrait panel, a hero needs one book, its cover art and a portrait panel, so
a single row trying to do all three would leave half its columns meaningless.
Separate rows also give the modes independent
schedules and filters, which is what you want anyway — "Fantasy shelves on
Sundays" alongside "five-star heroes daily".
"""

from uuid import UUID, uuid4

from pydantic import NaiveDatetime
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow

# A shelf is a row of spines across a landscape panel; a hero is one book's
# cover, which is portrait. Nothing is gained by letting an operator mismatch
# these, so orientation is derived from the mode rather than stored.
MODE_SHELF = "shelf"
MODE_HERO = "hero"
# Several stacked shelves on a portrait panel; a shelf is one landscape row.
MODE_BOOKCASE = "bookcase"


class CalibreSyncJob(SQLModel, table=True):
    """Recurring bookshelf job: select books from Calibre, generate, register."""

    __tablename__ = "calibre_sync_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, description="Unique job name")
    is_active: bool = Field(default=True)

    mode: str = Field(
        default=MODE_SHELF,
        description="'shelf' (a row of spines), 'bookcase' (stacked shelves, portrait) or 'hero' (one cover).",
    )
    target_device_profile_id: UUID = Field(
        foreign_key="device_profiles.id",
        description="Device profile this job generates for; provides target panel dimensions.",
    )
    prompt_preset_id: UUID = Field(
        foreign_key="prompt_presets.id",
        description="Prompt blocks to use when calling Gemini.",
    )

    # --- Which books are eligible (see BookFilter in the sync package) ---
    # Each list matches if *any* of its values match; the lists then AND
    # together. Empty means "no constraint on this axis".
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    languages: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    authors: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    books_per_shelf: int = Field(
        default=6,
        ge=2,
        le=12,
        description="Books on one shelf; ignored in hero mode.",
    )
    shelf_rows: int = Field(
        default=3,
        ge=2,
        le=5,
        description="Shelves stacked in one image; bookcase mode only.",
    )
    avoid_repeats: bool = Field(
        default=True,
        description="Skip books that are already on a live image, so none is on two walls at once.",
    )
    images_per_run: int = Field(default=1, ge=1, le=10)
    retention_days: int | None = Field(
        default=None,
        description="If set, generated images expire after this many days.",
    )

    # Spine lettering is wrong often enough that a generated shelf is checked
    # before it is kept: the image goes back to the model to be transcribed and
    # is regenerated when the titles do not match what was asked for.
    verify_spines: bool = Field(
        default=True,
        description="Read back spine text and regenerate on mismatch; shelf mode only.",
    )
    max_attempts: int = Field(
        default=4,
        ge=1,
        le=8,
        description="Generation attempts before the closest one is accepted anyway.",
    )

    # Scheduling lives on the job row (see ImmichSyncJob for the rationale).
    schedule_cron: str | None = Field(
        default=None,
        description="Five-field cron expression; None = manual runs only",
    )
    schedule_timezone: str = Field(default="UTC")
    next_run_at: NaiveDatetime | None = Field(
        default=None,
        description="When the job is next due; advanced by the claim-due hand-out",
    )
    last_run_at: NaiveDatetime | None = Field(
        default=None,
        description="Finish time of the most recent reported run",
    )

    # Set by the "Run now" endpoint; makes the job due immediately (active
    # or not) and the run report clears the flag.
    run_requested_at: NaiveDatetime | None = Field(default=None)

    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)
