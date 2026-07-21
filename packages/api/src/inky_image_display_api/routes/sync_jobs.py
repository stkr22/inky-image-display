"""REST endpoints for Immich sync job management."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import ImmichSyncJob
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import SyncJobCreate, SyncJobResponse, SyncJobUpdate
from inky_image_display_api.services.sync_job_scheduling import (
    begin_runs,
    claim_due_jobs,
    due_clause,
    next_cron_run,
)

router = APIRouter(prefix="/api/sync-jobs", tags=["sync-jobs"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[SyncJobResponse])
async def list_sync_jobs(
    request: Request,
    is_active: bool | None = None,
    due: bool | None = None,
) -> list[ImmichSyncJob]:
    """List sync jobs with optional filters.

    ``due=true`` is a pure read of what a claim would return — used by the
    worker's dry-run mode and diagnostics; it does not advance schedules.
    """
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(ImmichSyncJob)
        if is_active is not None:
            stmt = stmt.where(ImmichSyncJob.is_active == is_active)
        if due is True:
            stmt = stmt.where(due_clause(ImmichSyncJob, utcnow()))
        result = await session.exec(stmt)
        return list(result.all())


@router.post("/claim-due", response_model=list[SyncJobResponse])
async def claim_due_sync_jobs(request: Request) -> list[ImmichSyncJob]:
    """Hand out due jobs to the worker and advance their schedules (lease semantics)."""
    now = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        jobs = await claim_due_jobs(session, ImmichSyncJob, now)
        await begin_runs(session, "immich", [(j.id, j.name) for j in jobs], now)
        for job in jobs:
            # begin_runs committed and expired the instances; re-load them
            # so serialization doesn't hit a detached session.
            await session.refresh(job)
    if jobs:
        logger.info("Handed out %d due sync job(s)", len(jobs))
    return jobs


@router.get("/{job_id}", response_model=SyncJobResponse)
async def get_sync_job(request: Request, job_id: UUID) -> ImmichSyncJob:
    """Get a single sync job by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Sync job not found")
        return job


@router.post("", response_model=SyncJobResponse, status_code=201)
async def create_sync_job(request: Request, body: SyncJobCreate) -> ImmichSyncJob:
    """Create a new sync job."""
    job = ImmichSyncJob(**body.model_dump())
    if job.schedule_cron is not None:
        # Due immediately: a freshly created job should deliver right away.
        job.next_run_at = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    logger.info("Created sync job %s (%s)", job.id, job.name)
    return job


@router.put("/{job_id}", response_model=SyncJobResponse)
async def update_sync_job(request: Request, job_id: UUID, body: SyncJobUpdate) -> ImmichSyncJob:
    """Update an existing sync job."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Sync job not found")

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

    logger.info("Updated sync job %s", job_id)
    return job


@router.post("/{job_id}/run-now", response_model=SyncJobResponse)
async def request_sync_job_run(request: Request, job_id: UUID) -> ImmichSyncJob:
    """Flag a job for an out-of-band worker run and wake the worker.

    The worker claims flagged jobs (active or not — running a paused job
    on demand is the point of the button) and the posted run report
    clears the flag. The wake makes Run-now near-instant; if it is lost
    the worker's safety poll still picks the flag up.
    """
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Sync job not found")
        job.run_requested_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
    await request.app.state.mqtt.publish_wake("immich")
    logger.info("Run requested for sync job %s (%s)", job_id, job.name)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_sync_job(request: Request, job_id: UUID) -> None:
    """Delete a sync job."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Sync job not found")
        await session.delete(job)
        await session.commit()
    logger.info("Deleted sync job %s", job_id)
