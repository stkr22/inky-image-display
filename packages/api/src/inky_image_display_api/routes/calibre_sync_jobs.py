"""REST endpoints for Calibre bookshelf job management.

A near-twin of the Gemini job routes: same scheduling primitives, same
claim/run-now lease semantics, different payload. They are kept separate
rather than generalised because the shared surface is the four scheduling
helpers, and a generic job router would have to branch on job type for
everything else.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import CalibreSyncJob
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    CalibreSyncJobCreate,
    CalibreSyncJobResponse,
    CalibreSyncJobUpdate,
)
from inky_image_display_api.services.sync_job_scheduling import (
    begin_runs,
    claim_due_jobs,
    due_clause,
    next_cron_run,
)

router = APIRouter(prefix="/api/calibre/jobs", tags=["calibre"])
logger = logging.getLogger(__name__)


async def _load(session: AsyncSession, job_id: UUID) -> CalibreSyncJob:
    result = await session.exec(select(CalibreSyncJob).where(col(CalibreSyncJob.id) == job_id))
    job = result.first()
    if job is None:
        raise HTTPException(status_code=404, detail="Calibre sync job not found")
    return job


@router.get("", response_model=list[CalibreSyncJobResponse])
async def list_calibre_sync_jobs(
    request: Request,
    is_active: bool | None = None,
    due: bool | None = None,
) -> list[CalibreSyncJob]:
    """List Calibre bookshelf jobs with optional filters.

    ``due=true`` is a pure read of what a claim would return — used by the
    worker's dry-run mode; it does not advance schedules.
    """
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(CalibreSyncJob)
        if is_active is not None:
            stmt = stmt.where(CalibreSyncJob.is_active == is_active)
        if due is True:
            stmt = stmt.where(due_clause(CalibreSyncJob, utcnow()))
        result = await session.exec(stmt)
        return list(result.all())


@router.post("/claim-due", response_model=list[CalibreSyncJobResponse])
async def claim_due_calibre_jobs(request: Request) -> list[CalibreSyncJob]:
    """Hand out due Calibre jobs and advance their schedules (lease semantics)."""
    now = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        jobs = await claim_due_jobs(session, CalibreSyncJob, now)
        await begin_runs(session, "calibre", [(j.id, j.name) for j in jobs], now)
        for job in jobs:
            # begin_runs committed and expired the instances; re-load them
            # so serialization doesn't hit a detached session.
            await session.refresh(job)
    if jobs:
        logger.info("Handed out %d due calibre sync job(s)", len(jobs))
    return jobs


@router.get("/{job_id}", response_model=CalibreSyncJobResponse)
async def get_calibre_sync_job(request: Request, job_id: UUID) -> CalibreSyncJob:
    """Fetch a single Calibre bookshelf job by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        return await _load(session, job_id)


@router.post("", response_model=CalibreSyncJobResponse, status_code=201)
async def create_calibre_sync_job(request: Request, body: CalibreSyncJobCreate) -> CalibreSyncJob:
    """Create a new Calibre bookshelf job."""
    job = CalibreSyncJob(**body.model_dump())
    if job.schedule_cron is not None:
        # Due immediately: a freshly created job should deliver right away.
        job.next_run_at = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    logger.info("Created calibre sync job %s (%s, mode=%s)", job.id, job.name, job.mode)
    return job


@router.put("/{job_id}", response_model=CalibreSyncJobResponse)
async def update_calibre_sync_job(request: Request, job_id: UUID, body: CalibreSyncJobUpdate) -> CalibreSyncJob:
    """Patch an existing Calibre bookshelf job."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _load(session, job_id)
        update_data = body.model_dump(exclude_unset=True)
        if update_data.get("schedule_timezone") is None:
            # The column is non-nullable; an explicit null means "leave it".
            update_data.pop("schedule_timezone", None)
        for key, value in update_data.items():
            setattr(job, key, value)
        if "schedule_cron" in update_data or "schedule_timezone" in update_data:
            # Rebase the schedule on the new cadence (null cron = manual only).
            job.next_run_at = (
                None if job.schedule_cron is None else next_cron_run(job.schedule_cron, job.schedule_timezone, utcnow())
            )
        job.updated_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


@router.post("/{job_id}/run-now", response_model=CalibreSyncJobResponse)
async def request_calibre_job_run(request: Request, job_id: UUID) -> CalibreSyncJob:
    """Flag a Calibre job for an out-of-band worker run (see sync-jobs twin)."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _load(session, job_id)
        job.run_requested_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
    await request.app.state.mqtt.publish_wake("calibre")
    logger.info("Run requested for calibre sync job %s (%s)", job_id, job.name)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_calibre_sync_job(request: Request, job_id: UUID) -> None:
    """Delete a Calibre bookshelf job by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _load(session, job_id)
        await session.delete(job)
        await session.commit()
    logger.info("Deleted calibre sync job %s", job_id)
