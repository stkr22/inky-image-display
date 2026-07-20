"""REST endpoints for Gemini batch sync job management."""

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import GeminiSyncJob
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    GeminiSyncJobCreate,
    GeminiSyncJobResponse,
    GeminiSyncJobUpdate,
)
from inky_image_display_api.services.sync_job_scheduling import begin_runs, claim_due_jobs, due_clause

router = APIRouter(prefix="/api/genai/jobs", tags=["genai"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[GeminiSyncJobResponse])
async def list_gemini_sync_jobs(
    request: Request,
    is_active: bool | None = None,
    due: bool | None = None,
) -> list[GeminiSyncJob]:
    """List Gemini sync jobs with optional filters.

    ``due=true`` is a pure read of what a claim would return — used by the
    worker's dry-run mode; it does not advance schedules.
    """
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(GeminiSyncJob)
        if is_active is not None:
            stmt = stmt.where(GeminiSyncJob.is_active == is_active)
        if due is True:
            stmt = stmt.where(due_clause(GeminiSyncJob, utcnow()))
        result = await session.exec(stmt)
        return list(result.all())


@router.post("/claim-due", response_model=list[GeminiSyncJobResponse])
async def claim_due_gemini_jobs(request: Request) -> list[GeminiSyncJob]:
    """Hand out due Gemini jobs and advance their schedules (lease semantics)."""
    now = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        jobs = await claim_due_jobs(session, GeminiSyncJob, now)
        await begin_runs(session, "gemini", [(j.id, j.name) for j in jobs], now)
        for job in jobs:
            # begin_runs committed and expired the instances; re-load them
            # so serialization doesn't hit a detached session.
            await session.refresh(job)
    if jobs:
        logger.info("Handed out %d due gemini sync job(s)", len(jobs))
    return jobs


@router.get("/{job_id}", response_model=GeminiSyncJobResponse)
async def get_gemini_sync_job(request: Request, job_id: UUID) -> GeminiSyncJob:
    """Fetch a single Gemini sync job by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(GeminiSyncJob).where(col(GeminiSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Gemini sync job not found")
        return job


@router.post("", response_model=GeminiSyncJobResponse, status_code=201)
async def create_gemini_sync_job(request: Request, body: GeminiSyncJobCreate) -> GeminiSyncJob:
    """Create a new Gemini sync job."""
    job = GeminiSyncJob(**body.model_dump())
    if job.interval_minutes is not None:
        # Due immediately: a freshly created job should deliver right away.
        job.next_run_at = utcnow()
    async with AsyncSession(request.app.state.engine) as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    logger.info("Created gemini sync job %s (%s)", job.id, job.name)
    return job


@router.put("/{job_id}", response_model=GeminiSyncJobResponse)
async def update_gemini_sync_job(request: Request, job_id: UUID, body: GeminiSyncJobUpdate) -> GeminiSyncJob:
    """Patch an existing Gemini sync job."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(GeminiSyncJob).where(col(GeminiSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Gemini sync job not found")
        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(job, key, value)
        if "interval_minutes" in update_data:
            # Rebase the schedule on the new cadence (null = manual only).
            interval = job.interval_minutes
            job.next_run_at = None if interval is None else utcnow() + timedelta(minutes=interval)
        job.updated_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


@router.post("/{job_id}/run-now", response_model=GeminiSyncJobResponse)
async def request_gemini_job_run(request: Request, job_id: UUID) -> GeminiSyncJob:
    """Flag a Gemini job for an out-of-band worker run (see sync-jobs twin)."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(GeminiSyncJob).where(col(GeminiSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Gemini sync job not found")
        job.run_requested_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
    logger.info("Run requested for gemini sync job %s (%s)", job_id, job.name)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_gemini_sync_job(request: Request, job_id: UUID) -> None:
    """Delete a Gemini sync job by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(GeminiSyncJob).where(col(GeminiSyncJob.id) == job_id))
        job = result.first()
        if job is None:
            raise HTTPException(status_code=404, detail="Gemini sync job not found")
        await session.delete(job)
        await session.commit()
    logger.info("Deleted gemini sync job %s", job_id)
