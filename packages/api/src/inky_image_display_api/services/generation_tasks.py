"""In-process registry tracking on-demand Gemini generation tasks.

``POST /api/genai/generate`` returns a ``task_id`` and runs the actual
generation as a fire-and-forget background task — without this registry the
outcome (success, failure, which image) is only visible in server logs.
The registry keeps a bounded, in-memory history so the UI can answer "did
my generation work?" for the lifetime of the API process. Durability is
deliberately out of scope: a restart loses history but not images.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from uuid import UUID

# Bounded so a long-running process can't grow without limit; 100 entries
# comfortably covers "what happened recently" for a household deployment.
_MAX_TASKS = 100

TaskStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class GenerationTask:
    """Mutable status record for one generation request."""

    task_id: UUID
    subject: str
    status: TaskStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    image_id: UUID | None = None
    error: str | None = None
    # Free-text outcome note, e.g. "pushed to <device>" or "no online device".
    detail: str | None = None


class GenerationTaskRegistry:
    """Bounded FIFO registry of recent generation tasks.

    All mutation happens on the event loop (FastAPI background tasks run
    in-loop for async callables), so no locking is needed.
    """

    def __init__(self, max_tasks: int = _MAX_TASKS) -> None:
        """Initialise an empty registry holding at most ``max_tasks`` entries."""
        self._tasks: OrderedDict[UUID, GenerationTask] = OrderedDict()
        self._max_tasks = max_tasks

    def create(self, task_id: UUID, subject: str) -> GenerationTask:
        """Record a freshly queued task, evicting the oldest entry if full."""
        task = GenerationTask(task_id=task_id, subject=subject)
        self._tasks[task_id] = task
        while len(self._tasks) > self._max_tasks:
            self._tasks.popitem(last=False)
        return task

    def mark_running(self, task_id: UUID) -> None:
        """Transition a task to ``running`` (no-op if it was evicted)."""
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = "running"

    def mark_completed(self, task_id: UUID, *, image_id: UUID | None = None, detail: str | None = None) -> None:
        """Mark a task finished successfully with the produced image."""
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = "completed"
            task.finished_at = datetime.now(UTC)
            task.image_id = image_id
            task.detail = detail

    def mark_failed(self, task_id: UUID, error: str) -> None:
        """Mark a task as failed with a human-readable reason."""
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = "failed"
            task.finished_at = datetime.now(UTC)
            task.error = error

    def list_recent(self, limit: int = 50) -> list[GenerationTask]:
        """Return the most recent tasks, newest first."""
        return list(reversed(list(self._tasks.values())))[:limit]
