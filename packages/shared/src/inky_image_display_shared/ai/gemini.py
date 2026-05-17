"""Gemini image generation wrapper.

Renders composable prompt blocks into a final prompt and calls the Gemini
image model. Used by both the API service (on-demand generation) and the sync
service (batch jobs).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from google import genai
from google.genai import types

# Fallback model used when a preset/request leaves ``model_name`` unset.
# The active model is stored on each ``PromptPreset`` row so it can be tuned
# without redeploying — this constant only kicks in for legacy callers.
DEFAULT_MODEL = "gemini-2.5-flash-image"


class GeminiGenerationError(RuntimeError):
    """Raised when the Gemini API returns no usable image."""


@dataclass(frozen=True)
class RenderedPrompt:
    """The five composable prompt blocks for an e-ink illustration.

    Each block carries one concern of the final prompt. The composition
    block may contain a ``{subject}`` placeholder which is substituted at
    render time. The orientation flag controls the final orientation hint
    appended to the prompt and the aspect ratio used for the API call.
    """

    style: str
    palette: str
    legibility: str
    composition: str
    background: str
    is_portrait: bool

    def render(self, subject: str) -> str:
        """Assemble the final prompt string for a given subject."""
        composition = self.composition.format(subject=subject)
        orientation_hint = "Portrait orientation." if self.is_portrait else "Landscape orientation."
        return " ".join(
            [
                f"Bold illustrated portrait of {subject}.",
                self.style,
                composition,
                self.background,
                self.palette,
                self.legibility,
                orientation_hint,
            ]
        )

    @property
    def aspect_ratio(self) -> str:
        """Gemini ``aspect_ratio`` string matching the orientation flag."""
        return "3:4" if self.is_portrait else "4:3"


def _call_gemini_sync(api_key: str, model: str, prompt_text: str, aspect_ratio: str) -> bytes:
    """Blocking Gemini call. Returns raw image bytes from the first inline part."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        ),
    )
    candidates = response.candidates or []
    content = candidates[0].content if candidates else None
    parts = content.parts if content else None
    if not parts:
        raise GeminiGenerationError("Gemini returned no candidates or parts")
    for part in parts:
        if part.inline_data is None or part.inline_data.data is None:
            continue
        return part.inline_data.data
    raise GeminiGenerationError("Response contained no inline image data")


async def generate_image_bytes(
    api_key: str,
    prompt: RenderedPrompt,
    subject: str,
    *,
    model: str = DEFAULT_MODEL,
) -> bytes:
    """Call Gemini and return the raw generated image bytes.

    Resize/crop to the panel's exact dimensions is the API's responsibility
    (``POST /api/images/process``) — this helper just talks to Gemini. The
    SDK is synchronous, so the network call is offloaded to a worker thread.
    ``model`` defaults to :data:`DEFAULT_MODEL` for callers that haven't
    loaded a preset yet.
    """
    prompt_text = prompt.render(subject)
    return await asyncio.to_thread(_call_gemini_sync, api_key, model, prompt_text, prompt.aspect_ratio)
