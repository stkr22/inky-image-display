"""REST endpoints for prompt preset management."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import PromptPreset
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    PromptPresetCreate,
    PromptPresetResponse,
    PromptPresetUpdate,
)

router = APIRouter(prefix="/api/genai/presets", tags=["genai"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[PromptPresetResponse])
async def list_prompt_presets(request: Request) -> list[PromptPreset]:
    """List all prompt presets."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptPreset))
        return list(result.all())


@router.get("/{preset_id}", response_model=PromptPresetResponse)
async def get_prompt_preset(request: Request, preset_id: UUID) -> PromptPreset:
    """Fetch a single prompt preset by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptPreset).where(col(PromptPreset.id) == preset_id))
        preset = result.first()
        if preset is None:
            raise HTTPException(status_code=404, detail="Prompt preset not found")
        return preset


@router.post("", response_model=PromptPresetResponse, status_code=201)
async def create_prompt_preset(request: Request, body: PromptPresetCreate) -> PromptPreset:
    """Create a new prompt preset."""
    preset = PromptPreset(**body.model_dump())
    async with AsyncSession(request.app.state.engine) as session:
        session.add(preset)
        await session.commit()
        await session.refresh(preset)
    logger.info("Created prompt preset %s (%s)", preset.id, preset.name)
    return preset


@router.put("/{preset_id}", response_model=PromptPresetResponse)
async def update_prompt_preset(request: Request, preset_id: UUID, body: PromptPresetUpdate) -> PromptPreset:
    """Patch an existing prompt preset."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptPreset).where(col(PromptPreset.id) == preset_id))
        preset = result.first()
        if preset is None:
            raise HTTPException(status_code=404, detail="Prompt preset not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(preset, key, value)
        preset.updated_at = utcnow()
        session.add(preset)
        await session.commit()
        await session.refresh(preset)
    return preset


@router.delete("/{preset_id}", status_code=204)
async def delete_prompt_preset(request: Request, preset_id: UUID) -> None:
    """Delete a prompt preset by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptPreset).where(col(PromptPreset.id) == preset_id))
        preset = result.first()
        if preset is None:
            raise HTTPException(status_code=404, detail="Prompt preset not found")
        await session.delete(preset)
        await session.commit()
