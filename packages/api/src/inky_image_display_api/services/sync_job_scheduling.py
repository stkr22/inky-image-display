"""Due/claim scheduling shared by the Immich and Gemini sync-job routes.

Both job tables carry the same scheduling columns, so the due predicate and
the claim hand-out live here once instead of per twin. ``begin_runs`` is
shared with the display-job claim too: every claim records a ``running``
run row so the UI can tell "in progress" from "waiting for a worker".
"""

from datetime import datetime, timedelta
from uuid import UUID

from inky_image_display_shared.models import GeminiSyncJob, ImmichSyncJob, SyncJobRun
from sqlalchemy import ColumnElement
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

# A running row older than this whose worker never reported is abandoned
# (worker crashed / pod evicted); the next claim marks it as an error so
# the UI doesn't show a spinner forever.
_RUNNING_STALE_AFTER = timedelta(minutes=30)


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


async def begin_runs(session: AsyncSession, job_type: str, jobs: list[tuple[UUID, str]], now: datetime) -> None:
    """Record a ``running`` run row per claimed job; commits.

    ``jobs`` is ``(job_id, job_name)`` pairs. Stale running rows from a
    worker that died before reporting are closed as errors here — claim
    time is the natural moment, no separate sweep needed. The worker's
    posted report completes the fresh rows.
    """
    stale_result = await session.exec(
        select(SyncJobRun).where(
            col(SyncJobRun.job_type) == job_type,
            col(SyncJobRun.status) == "running",
            col(SyncJobRun.started_at) < now - _RUNNING_STALE_AFTER,
        )
    )
    for run in stale_result.all():
        run.status = "error"
        run.error = "Worker did not report back (crashed or restarted?)"
        run.finished_at = now
        session.add(run)
    for job_id, job_name in jobs:
        session.add(SyncJobRun(job_type=job_type, job_id=job_id, job_name=job_name, status="running", started_at=now))
    await session.commit()
