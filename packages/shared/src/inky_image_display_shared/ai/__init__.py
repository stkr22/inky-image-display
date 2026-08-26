"""AI image generation primitives shared by sync and api services."""

from .gemini import DEFAULT_MODEL, GeminiGenerationError, RenderedPrompt, generate_image_bytes
from .gemini_text import DEFAULT_TEXT_MODEL, MotdStory, generate_motd_story
from .gemini_vision import (
    DEFAULT_VISION_MODEL,
    ShelfReading,
    SpineReading,
    normalize_printed,
    spines_match,
    transcribe_spines,
)

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_TEXT_MODEL",
    "DEFAULT_VISION_MODEL",
    "GeminiGenerationError",
    "MotdStory",
    "RenderedPrompt",
    "ShelfReading",
    "SpineReading",
    "generate_image_bytes",
    "generate_motd_story",
    "normalize_printed",
    "spines_match",
    "transcribe_spines",
]
