"""AI image generation primitives shared by sync and api services."""

from .gemini import DEFAULT_MODEL, GeminiGenerationError, RenderedPrompt, generate_image_bytes

__all__ = [
    "DEFAULT_MODEL",
    "GeminiGenerationError",
    "RenderedPrompt",
    "generate_image_bytes",
]
