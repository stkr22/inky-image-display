"""Due/claim scheduling shared by the Immich and Gemini sync-job routes.

Both job tables carry the same scheduling columns, so the due predicate and
the claim hand-out live here once instead of per twin.
"""

from datetime import datetime, timedelta

from inky_image_display_shared.models import GeminiSyncJob, ImmichSyncJob
from sqlalchemy import ColumnElement
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession


def due_clause[JobT: (ImmichSyncJob, GeminiSyncJob)](model: type[JobT], now: datetime) -> ColumnElement[bool]:
    """Jobs the worker should run: Run-now flagged, or on-schedule and due.

    Run-now works on paused jobs on purpose — running a paused job on
    demand is the point of the button.
    """
    return or_(
        col(model.run_requested_at).is_not(None),
        (col(model.is_active).is_(True)) & (col(model.interval_minutes).is_not(None)) & (col(model.next_run_at) <= now),
    )


async def claim_due_jobs[JobT: (ImmichSyncJob, GeminiSyncJob)](
    session: AsyncSession, model: type[JobT], now: datetime
) -> list[JobT]:
    """Hand out due jobs and advance their schedules.

    Advancing ``next_run_at`` at hand-out doubles as a lease: an overlapping
    worker invocation won't be given the same interval-due job twice. The
    Run-now flag is deliberately NOT cleared here — the posted run report
    clears it, so a worker that dies mid-run leaves the request armed.
    """
    result = await session.exec(select(model).where(due_clause(model, now)))
    jobs = list(result.all())
    for job in jobs:
        if job.interval_minutes is not None:
            job.next_run_at = now + timedelta(minutes=job.interval_minutes)
            session.add(job)
    await session.commit()
    for job in jobs:
        await session.refresh(job)
    return jobs
