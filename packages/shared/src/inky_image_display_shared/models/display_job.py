"""Display job models.

A display job is a pure content generator: it renders screens (one per
grid slot at the slot device's native resolution) into a message group on
its own cadence. *Displaying* those groups is the target grid's business —
the grid carries the display schedule and session state (see ``grid``),
so a job can pre-generate content long before the grid shows it. The MOTD
is the first job type; new content formats (quotes,
art-with-explanation, …) are further job types that reuse the same grid
targeting and generation machinery.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.time import utcnow


class DisplayJob(SQLModel, table=True):
    """A content-generation job targeting one grid.

    Content-generation fields (prompt, source mode, preset, text model) are
    typed columns rather than an opaque JSON blob so the preset FK keeps
    its SET NULL behaviour; they are generic enough that future text-based
    job types can reuse them.

    Scheduling matches the sync jobs (interval + next-run lease) so all job
    kinds read the same in the Jobs UI; ``interval_minutes`` ``None`` means
    manual generation only.
    """

    __tablename__ = "display_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    # Discriminator for the content pipeline; "motd" is the only type today.
    job_type: str = Field(default="motd")
    # The grid whose slots this job renders for. SET NULL keeps the job (and
    # its generated history) when the grid is deleted; a job without a grid
    # is inert until re-targeted.
    target_grid_id: UUID | None = Field(default=None, foreign_key="grids.id", ondelete="SET NULL")

    # Content generation.
    content_prompt: str = Field(default=DEFAULT_MOTD_PROMPT)
    # "grounded" uses Google Search grounding for a real recent story with a
    # source URL; "knowledge" asks the model for a timeless/historical story.
    source_mode: str = Field(default="grounded")
    image_preset_id: UUID | None = Field(default=None, foreign_key="prompt_presets.id", ondelete="SET NULL")
    text_model_name: str = Field(default="gemini-2.5-flash")

    # Generation cadence and worker hand-off, identical to the sync jobs:
    # the external worker claims due jobs (``next_run_at`` advanced as a
    # lease at claim) and generates the content out of process.
    is_active: bool = Field(default=True)
    interval_minutes: int | None = Field(default=None, ge=1)
    next_run_at: datetime | None = Field(default=None)
    last_run_at: datetime | None = Field(default=None)
    run_requested_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})


class DisplayJobSlot(SQLModel, table=True):
    """Which content part one grid slot shows.

    Slots address grid positions (``row``/``col`` on ``grid_devices``), not
    devices, so swapping a panel in the grid layout keeps the job mapping
    intact. ``parts`` is a JSON-encoded list of part keys (see
    ``inky_image_display_shared.motd``). Groups are frozen spreads — one
    image per slot — so only the first part of a slot is ever shown;
    configure one part per slot.
    """

    __tablename__ = "display_job_slots"

    job_id: UUID = Field(foreign_key="display_jobs.id", primary_key=True, ondelete="CASCADE")
    row: int = Field(primary_key=True)
    col: int = Field(primary_key=True)
    parts: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utcnow)
