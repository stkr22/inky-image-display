"""REST endpoints for Gemini batch sync job management."""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import GeminiSyncJob
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    GeminiSyncJobCreate,
    GeminiSyncJobResponse,
    GeminiSyncJobUpdate,
)

router = APIRouter(prefix="/api/genai/jobs", tags=["genai"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[GeminiSyncJobResponse])
async def list_gemini_sync_jobs(request: Request, is_active: bool | None = None) -> list[GeminiSyncJob]:
    """List Gemini sync jobs, optionally filtered by ``is_active``."""
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(GeminiSyncJob)
        if is_active is not None:
            stmt = stmt.where(GeminiSyncJob.is_active == is_active)
        result = await session.exec(stmt)
        return list(result.all())


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
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(job, key, value)
        job.updated_at = datetime.now()
        session.add(job)
        await session.commit()
        await session.refresh(job)
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
