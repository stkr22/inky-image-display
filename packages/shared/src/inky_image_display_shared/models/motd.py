"""Generated MOTD content models.

An MOTD-type display job (see ``display_job``) generates one positive
daily story per run. Stories are persisted as ``MotdMessage`` rows with
pre-rendered ``MotdScreen`` images per part and panel size, so displaying
is a plain push of exact-size JPEGs — the controller needs no MOTD
awareness.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class MotdMessage(SQLModel, table=True):
    """One generated story with its structured content parts."""

    __tablename__ = "motd_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_id: UUID = Field(foreign_key="display_jobs.id", ondelete="CASCADE")
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
    # When this message was last put on the displays (manual or scheduled).
    # Surfaced in the history list so operators can avoid repeats.
    displayed_at: datetime | None = Field(default=None)

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
