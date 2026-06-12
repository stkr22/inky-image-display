"""REST endpoints for prompt block management."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import PromptBlock
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    PromptBlockCreate,
    PromptBlockResponse,
    PromptBlockUpdate,
)

router = APIRouter(prefix="/api/genai/blocks", tags=["genai"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[PromptBlockResponse])
async def list_prompt_blocks(request: Request, kind: str | None = None) -> list[PromptBlock]:
    """List prompt blocks, optionally filtered by ``kind``."""
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(PromptBlock)
        if kind is not None:
            stmt = stmt.where(PromptBlock.kind == kind)
        result = await session.exec(stmt)
        return list(result.all())


@router.get("/{block_id}", response_model=PromptBlockResponse)
async def get_prompt_block(request: Request, block_id: UUID) -> PromptBlock:
    """Fetch a single prompt block by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptBlock).where(col(PromptBlock.id) == block_id))
        block = result.first()
        if block is None:
            raise HTTPException(status_code=404, detail="Prompt block not found")
        return block


@router.post("", response_model=PromptBlockResponse, status_code=201)
async def create_prompt_block(request: Request, body: PromptBlockCreate) -> PromptBlock:
    """Create a new prompt block."""
    block = PromptBlock(**body.model_dump())
    async with AsyncSession(request.app.state.engine) as session:
        session.add(block)
        await session.commit()
        await session.refresh(block)
    logger.info("Created prompt block %s (%s/%s)", block.id, block.kind, block.name)
    return block


@router.put("/{block_id}", response_model=PromptBlockResponse)
async def update_prompt_block(request: Request, block_id: UUID, body: PromptBlockUpdate) -> PromptBlock:
    """Patch an existing prompt block."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptBlock).where(col(PromptBlock.id) == block_id))
        block = result.first()
        if block is None:
            raise HTTPException(status_code=404, detail="Prompt block not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(block, key, value)
        block.updated_at = utcnow()
        session.add(block)
        await session.commit()
        await session.refresh(block)
    return block


@router.delete("/{block_id}", status_code=204)
async def delete_prompt_block(request: Request, block_id: UUID) -> None:
    """Delete a prompt block by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(PromptBlock).where(col(PromptBlock.id) == block_id))
        block = result.first()
        if block is None:
            raise HTTPException(status_code=404, detail="Prompt block not found")
        await session.delete(block)
        await session.commit()
