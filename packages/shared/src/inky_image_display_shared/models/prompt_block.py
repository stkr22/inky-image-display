"""Prompt block model — atomic, reusable text fragment for AI image prompts.

A prompt for the Gemini image model is composed of five concerns: style,
palette, legibility, composition, and background. Each concern lives as its
own row so users can mix-and-match wording across presets (e.g. swap a
humanoid composition for a landscape one without rewriting the rest).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class PromptBlock(SQLModel, table=True):
    """One reusable prompt fragment, scoped to a single concern (``kind``)."""

    __tablename__ = "prompt_blocks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: str = Field(
        index=True,
        description="One of: style, palette, legibility, composition, background.",
    )
    name: str = Field(description="Unique within a kind; identifies this block in the UI.")
    text: str = Field(description="Prompt fragment text. May contain {subject} placeholder.")
    is_default: bool = Field(
        default=False,
        description="At most one block per kind should have this set; used as fallback.",
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
