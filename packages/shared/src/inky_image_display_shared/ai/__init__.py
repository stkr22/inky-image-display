"""AI image generation primitives shared by sync and api services."""

from .gemini import DEFAULT_MODEL, GeminiGenerationError, RenderedPrompt, generate_image_bytes
from .gemini_text import DEFAULT_TEXT_MODEL, MotdStory, generate_motd_story

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_TEXT_MODEL",
    "GeminiGenerationError",
    "MotdStory",
    "RenderedPrompt",
    "generate_image_bytes",
    "generate_motd_story",
]
