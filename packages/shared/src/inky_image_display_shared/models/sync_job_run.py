"""Persisted history of sync worker runs.

The sync workers execute as cron jobs on another machine; without a
persisted run record the only feedback after editing a job is "wait for
the next cron and read the worker logs". Each completed job run POSTs one
row here so the UI can answer "did it work, and what did it do?" per job.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class SyncJobRun(SQLModel, table=True):
    """Outcome summary of one worker run of one sync job.

    ``job_id`` is a plain UUID (no FK) on purpose: runs are a log, and a
    deleted job shouldn't erase the history that explains where its images
    came from — ``job_name`` keeps rows readable after deletion.

    Attributes:
        id: Unique identifier.
        job_type: Which worker produced the run ("immich" or "gemini").
        job_id: UUID of the job at run time.
        job_name: Job name at run time (denormalized for display).
        status: "success" or "error".
        started_at: When the worker began the job.
        finished_at: When the worker finished the job.
        images_added: Newly downloaded/generated images.
        images_skipped: Candidates skipped (already synced, undersized, ...).
        images_deleted: Images removed by retention cleanup.
        detail: Free-text summary from the worker.
        error: First error message when status is "error".
        created_at: When the row was recorded.

    """

    __tablename__ = "sync_job_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_type: str = Field(index=True, description="'immich' or 'gemini'")
    job_id: UUID = Field(index=True)
    job_name: str
    status: str = Field(description="'success' or 'error'")
    started_at: datetime
    finished_at: datetime
    images_added: int = Field(default=0)
    images_skipped: int = Field(default=0)
    images_deleted: int = Field(default=0)
    detail: str | None = Field(default=None)
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
