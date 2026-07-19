"""Display job models.

A display job produces content for a grid: it generates screens (one per
grid slot at the slot device's native resolution), claims the grid's
panels for a session, rotates multi-part slots, and releases the grid when
the session ends. The MOTD is the first job type; new content formats
(quotes, art-with-explanation, …) are further job types that reuse the
same grid targeting, scheduling and session machinery.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.time import utcnow


class DisplayJob(SQLModel, table=True):
    """A content job targeting one grid, with schedule and session state.

    Content-generation fields (prompt, source mode, preset, text model) are
    typed columns rather than an opaque JSON blob so the preset FK keeps
    its SET NULL behaviour; they are generic enough that future text-based
    job types can reuse them.
    """

    __tablename__ = "display_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    # Discriminator for the content pipeline; "motd" is the only type today.
    job_type: str = Field(default="motd")
    # The grid whose panels this job fills. SET NULL keeps the job (and its
    # generated history) when the grid is deleted; a job without a grid is
    # inert until re-targeted.
    target_grid_id: UUID | None = Field(default=None, foreign_key="grids.id", ondelete="SET NULL")

    # Content generation.
    content_prompt: str = Field(default=DEFAULT_MOTD_PROMPT)
    # "grounded" uses Google Search grounding for a real recent story with a
    # source URL; "knowledge" asks the model for a timeless/historical story.
    source_mode: str = Field(default="grounded")
    image_preset_id: UUID | None = Field(default=None, foreign_key="prompt_presets.id", ondelete="SET NULL")
    text_model_name: str = Field(default="gemini-2.5-flash")

    # Daily display schedule. ``display_time`` is a local wall-clock "HH:MM"
    # in ``timezone`` — the repo is otherwise UTC-everywhere, but a "show at
    # 08:00" schedule only makes sense in the operator's local time.
    schedule_enabled: bool = Field(default=False)
    display_time: str = Field(default="08:00")
    # Bitmask of active weekdays, bit 0 = Monday … bit 6 = Sunday.
    weekday_mask: int = Field(default=127)
    timezone: str = Field(default="UTC")
    # Generate the day's content this many minutes ahead of display time so
    # the scheduled display pushes an already-rendered message.
    generation_lead_minutes: int = Field(default=60)

    # ``None`` shows the content until the operator releases it manually.
    display_duration_seconds: int | None = Field(default=None)

    # Live session state. ``active_message_id`` is intentionally not a FK:
    # motd_messages already references display_jobs, and a back-reference
    # would create a circular FK that complicates table creation order.
    active_message_id: UUID | None = Field(default=None)
    active_since: datetime | None = Field(default=None)
    active_expires_at: datetime | None = Field(default=None)

    # Once-per-day guards for the scheduler tick, tracked as local dates in
    # ``timezone`` so "today" matches the operator's calendar.
    last_generated_on: date | None = Field(default=None)
    last_displayed_on: date | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})


class DisplayJobSlot(SQLModel, table=True):
    """Which content parts one grid slot shows, in rotation order.

    Slots address grid positions (``row``/``col`` on ``grid_devices``), not
    devices, so swapping a panel in the grid layout keeps the job mapping
    intact. ``parts`` is a JSON-encoded ordered list of part keys (see
    ``inky_image_display_shared.motd``); ``rotation_index`` is session
    state — the position currently on screen, advanced on each refresh of
    a multi-part slot while the session is active.
    """

    __tablename__ = "display_job_slots"

    job_id: UUID = Field(foreign_key="display_jobs.id", primary_key=True, ondelete="CASCADE")
    row: int = Field(primary_key=True)
    col: int = Field(primary_key=True)
    parts: str = Field(default="[]")
    rotation_index: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
