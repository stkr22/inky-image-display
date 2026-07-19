"""Run history for sync jobs (Immich and Gemini batch).

The workers POST one report per completed job run; the UI reads them to
show per-job "last run" summaries. One shared resource for both job types
keeps the worker contract and the UI query identical.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Request
from inky_image_display_shared.models import GeminiSyncJob, ImmichSyncJob, SyncJobRun
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import SyncJobRunReport, SyncJobRunResponse

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
        query = query.order_by(col(SyncJobRun.finished_at).desc()).limit(limit)
        result = await session.exec(query)
        return list(result.all())


@router.post("", response_model=SyncJobRunResponse, status_code=201)
async def report_sync_run(request: Request, body: SyncJobRunReport) -> SyncJobRun:
    """Record a completed worker run and clear the job's run-now flag.

    Clearing ``run_requested_at`` here (rather than when the worker picks
    the job up) means a worker that dies mid-run leaves the request armed,
    so the next --requested-only cron retries instead of silently dropping
    the operator's click.
    """
    run = SyncJobRun(
        job_type=body.job_type,
        job_id=body.job_id,
        job_name=body.job_name,
        status=body.status,
        started_at=body.started_at,
        finished_at=body.finished_at,
        images_added=body.images_added,
        images_skipped=body.images_skipped,
        images_deleted=body.images_deleted,
        detail=body.detail,
        error=body.error,
    )
    async with AsyncSession(request.app.state.engine) as session:
        session.add(run)

        job_model = ImmichSyncJob if body.job_type == "immich" else GeminiSyncJob
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
            .order_by(col(SyncJobRun.finished_at).desc())
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
