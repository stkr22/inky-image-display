"""Prompt preset — a named bundle of one block per kind.

Jobs and on-demand generation requests reference a preset by id; the API
resolves it to five block texts before calling Gemini.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class PromptPreset(SQLModel, table=True):
    """A named bundle of five prompt blocks (one per kind)."""

    __tablename__ = "prompt_presets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    style_block_id: UUID = Field(foreign_key="prompt_blocks.id")
    palette_block_id: UUID = Field(foreign_key="prompt_blocks.id")
    legibility_block_id: UUID = Field(foreign_key="prompt_blocks.id")
    composition_block_id: UUID = Field(foreign_key="prompt_blocks.id")
    background_block_id: UUID = Field(foreign_key="prompt_blocks.id")
    model_name: str = Field(
        default="gemini-2.5-flash-image",
        description="Gemini image model used when this preset is selected.",
    )
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
