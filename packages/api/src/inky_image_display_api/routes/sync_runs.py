"""Run history for sync jobs (Immich and Gemini batch).

The workers POST one report per completed job run; the UI reads them to
show per-job "last run" summaries. One shared resource for both job types
keeps the worker contract and the UI query identical.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Request
from inky_image_display_shared.models import DisplayJob, GeminiSyncJob, ImmichSyncJob, SyncJobRun
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import SyncJobRunReport, SyncJobRunResponse

_JOB_MODELS = {"immich": ImmichSyncJob, "gemini": GeminiSyncJob, "display": DisplayJob}

router = APIRouter(prefix="/api/sync-runs", tags=["sync-runs"])
logger = logging.getLogger(__name__)

# Runs are diagnostics, not an audit log: keep enough to see a trend per
# job, prune the rest so a frequent cron can't grow the table unbounded.
_MAX_RUNS_PER_JOB = 20


@router.get("", response_model=list[SyncJobRunResponse])
async def list_sync_runs(
    request: Request,
    job_type: str | None = None,
    job_id: UUID | None = None,
    limit: int = 100,
) -> list[SyncJobRun]:
    """List run reports, newest first, optionally filtered by job."""
    async with AsyncSession(request.app.state.engine) as session:
        query = select(SyncJobRun)
        if job_type is not None:
            query = query.where(SyncJobRun.job_type == job_type)
        if job_id is not None:
            query = query.where(SyncJobRun.job_id == job_id)
        query = query.order_by(col(SyncJobRun.started_at).desc()).limit(limit)
        result = await session.exec(query)
        return list(result.all())


@router.post("", response_model=SyncJobRunResponse, status_code=201)
async def report_sync_run(request: Request, body: SyncJobRunReport) -> SyncJobRun:
    """Record a completed worker run and clear the job's run-now flag.

    The claim endpoint already created a ``running`` row for this job; the
    report completes that row so the UI's spinner resolves into a result.
    A report without a matching running row (older worker, direct --all
    invocation) still records a fresh row. Clearing ``run_requested_at``
    here (rather than at claim) means a worker that dies mid-run leaves
    the request armed, so the next cron retries instead of silently
    dropping the operator's click.
    """
    async with AsyncSession(request.app.state.engine) as session:
        running_result = await session.exec(
            select(SyncJobRun)
            .where(
                col(SyncJobRun.job_type) == body.job_type,
                col(SyncJobRun.job_id) == body.job_id,
                col(SyncJobRun.status) == "running",
            )
            .order_by(col(SyncJobRun.started_at).desc())
        )
        run = running_result.first()
        if run is None:
            run = SyncJobRun(
                job_type=body.job_type,
                job_id=body.job_id,
                job_name=body.job_name,
                status=body.status,
                started_at=body.started_at,
            )
        run.status = body.status
        run.started_at = body.started_at
        run.finished_at = body.finished_at
        run.images_added = body.images_added
        run.images_skipped = body.images_skipped
        run.images_deleted = body.images_deleted
        run.detail = body.detail
        run.error = body.error
        session.add(run)

        job_model = _JOB_MODELS.get(body.job_type, ImmichSyncJob)
        job_result = await session.exec(select(job_model).where(col(job_model.id) == body.job_id))
        job = job_result.first()
        if job is not None:
            job.last_run_at = body.finished_at
            if job.run_requested_at is not None and job.run_requested_at <= body.started_at:
                job.run_requested_at = None
            session.add(job)

        # Prune per (type, id) beyond the retention window. Autoflush has
        # already inserted the new row, so the offset keeps exactly
        # _MAX_RUNS_PER_JOB rows including it.
        stale = await session.exec(
            select(SyncJobRun)
            .where(SyncJobRun.job_type == body.job_type, SyncJobRun.job_id == body.job_id)
            .order_by(col(SyncJobRun.started_at).desc())
            .offset(_MAX_RUNS_PER_JOB)
        )
        for old in stale.all():
            await session.delete(old)

        await session.commit()
        await session.refresh(run)

    logger.info(
        "Recorded %s run for job %s (%s): +%d images, status=%s",
        body.job_type,
        body.job_name,
        body.job_id,
        body.images_added,
        body.status,
    )
    return run
