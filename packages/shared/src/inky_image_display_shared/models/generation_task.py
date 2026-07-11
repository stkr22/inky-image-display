"""Persisted status of on-demand AI generation tasks.

Replaces the previous in-process registry: generation history used to
vanish on every API restart, which read as "my generation was lost" in the
UI. Rows are pruned to a bounded recent window — this is operational
visibility ("did my generation work?"), not an audit log.
"""

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class GenerationTask(SQLModel, table=True):
    """Status record for one on-demand generation request.

    Attributes:
        task_id: Identifier returned by POST /api/genai/generate.
        subject: What was asked for (or "message of the day").
        status: queued / running / completed / failed.
        created_at: When the task was queued.
        finished_at: When it completed or failed.
        image_id: Resulting image, when one was produced. Plain UUID, no
            FK: deleting the image must not erase the task history line.
        error: Failure reason when status is "failed".
        detail: Free-text outcome note, e.g. "Pushed to <device>".

    """

    __tablename__ = "generation_tasks"

    task_id: UUID = Field(primary_key=True)
    subject: str
    status: str = Field(default="queued", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    image_id: UUID | None = Field(default=None)
    error: str | None = Field(default=None)
    detail: str | None = Field(default=None)
