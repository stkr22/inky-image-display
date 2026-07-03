"""Message-of-the-day models.

A single ``MotdConfig`` row describes how the daily message is generated
(prompt, source mode, image preset), which devices participate and which
content parts each shows, when it is displayed (daily schedule and/or
manual trigger) and for how long. Generated stories are persisted as
``MotdMessage`` rows with pre-rendered ``MotdScreen`` images per part and
panel size, so displaying is a plain push of exact-size JPEGs — the
controller needs no MOTD awareness.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.time import utcnow


class MotdConfig(SQLModel, table=True):
    """Operator configuration plus live session state for the MOTD.

    One config drives one MOTD at a time; session state (which message is
    showing, since when, until when) lives directly on the row rather than
    in a separate session table.
    """

    __tablename__ = "motd_configs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

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
    # Generate the day's message this many minutes ahead of display time so
    # the scheduled display pushes an already-rendered message.
    generation_lead_minutes: int = Field(default=60)

    # ``None`` shows the message until the operator releases it manually.
    display_duration_seconds: int | None = Field(default=None)

    # Live session state. ``active_message_id`` is intentionally not a FK:
    # motd_messages already references motd_configs, and a back-reference
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


class MotdDeviceAssignment(SQLModel, table=True):
    """Which content parts a participating device shows, in rotation order.

    ``parts`` is a JSON-encoded ordered list of part keys (see
    ``inky_image_display_shared.motd``), e.g. ``["what", "why", "qr"]``.
    ``rotation_index`` is session state: the position in that list currently
    on screen, advanced at each device refresh while the MOTD is active.
    """

    __tablename__ = "motd_device_assignments"

    config_id: UUID = Field(foreign_key="motd_configs.id", primary_key=True, ondelete="CASCADE")
    device_id: UUID = Field(foreign_key="devices.id", primary_key=True, ondelete="CASCADE")
    parts: str = Field(default="[]")
    rotation_index: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)


class MotdMessage(SQLModel, table=True):
    """One generated story with its structured content parts."""

    __tablename__ = "motd_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    config_id: UUID = Field(foreign_key="motd_configs.id", ondelete="CASCADE")
    status: str = Field(default="generating")  # generating | ready | failed
    error: str | None = Field(default=None)

    headline: str | None = Field(default=None)
    what: str | None = Field(default=None)
    why: str | None = Field(default=None)
    # "when" is a SQL keyword and shadows Python syntax highlighting; the
    # column is named when_text to keep raw-SQL debugging painless.
    when_text: str | None = Field(default=None)
    takeaway: str | None = Field(default=None)
    # One-sentence visual scene handed to the image model as its subject.
    image_subject: str | None = Field(default=None)
    # Only ever taken from Gemini grounding metadata, never from model text —
    # None means the QR part is skipped for this message.
    source_url: str | None = Field(default=None)
    source_title: str | None = Field(default=None)
    source_mode: str = Field(default="grounded")

    created_at: datetime = Field(default_factory=utcnow)


class MotdScreen(SQLModel, table=True):
    """A pre-rendered screen for one part at one panel size.

    Deliberately not an ``Image`` row: keeping MOTD screens in their own
    table keeps them out of normal FIFO rotation without scoping filters,
    and ``DisplayCommand.image_id`` is a free-form tracking string so
    pushing these ids is safe.
    """

    __tablename__ = "motd_screens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    message_id: UUID = Field(foreign_key="motd_messages.id", ondelete="CASCADE")
    part: str
    width: int
    height: int
    is_portrait: bool = Field(default=False)
    storage_path: str
    created_at: datetime = Field(default_factory=utcnow)
