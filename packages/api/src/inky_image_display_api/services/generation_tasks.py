"""DB-backed registry tracking on-demand Gemini generation tasks.

``POST /api/genai/generate`` returns a ``task_id`` and runs the actual
generation as a fire-and-forget background task — this store is what lets
the UI answer "did my generation work?". It used to be an in-process dict,
which meant every API restart wiped the history mid-flight (a fact the UI
had to apologise for in a caption); rows now live in the ``generation_tasks``
table and survive restarts. History stays bounded by pruning on insert.

Status writes deliberately swallow "row not found": a pruned task simply
stops reporting, mirroring the old registry's eviction behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from inky_image_display_shared.models import GenerationTask
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncEngine

# Bounded so a long-running deployment can't grow the table without limit;
# 200 entries comfortably covers "what happened recently" for a household.
_MAX_TASKS = 200


def task_registry(request: Request) -> GenerationTaskStore:
    """Return the app-wide task store, creating it lazily.

    Lazy creation keeps test apps (which assemble ``app.state`` by hand)
    working without extra fixtures.
    """
    registry = getattr(request.app.state, "generation_tasks", None)
    if registry is None:
        registry = GenerationTaskStore(request.app.state.engine)
        request.app.state.generation_tasks = registry
    return registry


class GenerationTaskStore:
    """Bounded, persistent history of recent generation tasks."""

    def __init__(self, engine: AsyncEngine, max_tasks: int = _MAX_TASKS) -> None:
        """Store the engine; each operation opens its own short session."""
        self._engine = engine
        self._max_tasks = max_tasks

    async def create(self, task_id: UUID, subject: str) -> None:
        """Record a freshly queued task, pruning the oldest beyond the cap."""
        async with AsyncSession(self._engine) as session:
            session.add(GenerationTask(task_id=task_id, subject=subject))
            # Autoflush includes the row added above, so the offset keeps
            # exactly max_tasks rows (newest first) including the new one.
            stale = await session.exec(
                select(GenerationTask).order_by(col(GenerationTask.created_at).desc()).offset(self._max_tasks)
            )
            for old in stale.all():
                await session.delete(old)
            await session.commit()

    async def mark_running(self, task_id: UUID) -> None:
        """Transition a task to ``running`` (no-op if it was pruned)."""
        await self._update(task_id, status="running")

    async def mark_completed(self, task_id: UUID, *, image_id: UUID | None = None, detail: str | None = None) -> None:
        """Mark a task finished successfully with the produced image."""
        await self._update(task_id, status="completed", finished=True, image_id=image_id, detail=detail)

    async def mark_failed(self, task_id: UUID, error: str) -> None:
        """Mark a task as failed with a human-readable reason."""
        await self._update(task_id, status="failed", finished=True, error=error)

    async def list_recent(self, limit: int = 50) -> list[GenerationTask]:
        """Return the most recent tasks, newest first."""
        async with AsyncSession(self._engine) as session:
            result = await session.exec(
                select(GenerationTask).order_by(col(GenerationTask.created_at).desc()).limit(limit)
            )
            return list(result.all())

    async def _update(  # noqa: PLR0913 — keyword-only status fields
        self,
        task_id: UUID,
        *,
        status: str,
        finished: bool = False,
        image_id: UUID | None = None,
        error: str | None = None,
        detail: str | None = None,
    ) -> None:
        async with AsyncSession(self._engine) as session:
            result = await session.exec(select(GenerationTask).where(col(GenerationTask.task_id) == task_id))
            task = result.first()
            if task is None:
                return
            task.status = status
            if finished:
                task.finished_at = utcnow()
            if image_id is not None:
                task.image_id = image_id
            if error is not None:
                task.error = error
            if detail is not None:
                task.detail = detail
            session.add(task)
            await session.commit()
