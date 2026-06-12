"""REST endpoints for Immich sync job management."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import ImmichSyncJob
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import SyncJobCreate, SyncJobResponse, SyncJobUpdate

router = APIRouter(prefix="/api/sync-jobs", tags=["sync-jobs"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[SyncJobResponse])
async def list_sync_jobs(
    request: Request,
    is_active: bool | None = None,
) -> list[ImmichSyncJob]:
    """List sync jobs with optional active filter."""
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(ImmichSyncJob)
        if is_active is not None:
            stmt = stmt.where(ImmichSyncJob.is_active == is_active)
        result = await session.exec(stmt)
        return list(result.all())


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
        for key, value in update_data.items():
            setattr(job, key, value)
        job.updated_at = utcnow()

        session.add(job)
        await session.commit()
        await session.refresh(job)

    logger.info("Updated sync job %s", job_id)
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
