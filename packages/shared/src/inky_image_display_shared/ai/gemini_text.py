"""Gemini text generation for the message-of-the-day story.

Produces one structured positive story per call. Two modes:

- grounded: uses the Google Search tool so the story is a real, recent news
  item with a verifiable source URL. Grounding and JSON response schemas
  cannot be combined in a single Gemini call, so this runs two steps —
  a grounded free-text call, then a structuring call over its output. The
  source URL is taken exclusively from grounding metadata, never from model
  text, because models fabricate plausible-looking URLs.
- knowledge: a single structured call drawing on model knowledge, for
  timeless/historical stories. No source URL is produced.
"""

from __future__ import annotations

import asyncio
import json

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from inky_image_display_shared.ai.gemini import GeminiGenerationError

DEFAULT_TEXT_MODEL = "gemini-2.5-flash"


class MotdStory(BaseModel):
    """Structured story fields, one per displayable content part."""

    headline: str
    what: str
    why: str
    when_text: str
    takeaway: str
    image_subject: str
    source_title: str | None = None


# Appended in code (not part of the operator-editable prompt) so prompt
# edits can steer topic and tone but cannot break the parsing contract.
_STRUCTURE_INSTRUCTIONS = """\
Decompose the story into these fields:
- headline: the story in at most 8 words.
- what: what happened — 1-2 short, plain-language sentences.
- why: why it matters — 1-2 short sentences.
- when_text: when it happened — one short phrase or sentence.
- takeaway: the takeaway message for the reader — one short sentence.
- image_subject: one sentence describing a concrete visual scene an image \
model can paint to accompany the story. Describe only the scene; it must \
not contain any text or lettering.
- source_title: the name of the publication or source if known, else null.
The text is shown on small e-ink screens, so keep every field short."""

_GROUNDED_RESEARCH_SUFFIX = """\

Use Google Search to find one such TRUE story from roughly the last seven \
days. Retell it faithfully — what happened, why it matters, and when — and \
name the publication it came from. Do not invent or embellish facts."""

_KNOWLEDGE_SUFFIX = """\

Choose one well-documented true story (it may be historical). Do not \
invent facts. """


def _first_grounding_source(response: types.GenerateContentResponse) -> tuple[str | None, str | None]:
    """Extract (url, title) from the first web grounding chunk, if any."""
    candidates = response.candidates or []
    metadata = candidates[0].grounding_metadata if candidates else None
    for chunk in (metadata.grounding_chunks if metadata else None) or []:
        if chunk.web is not None and chunk.web.uri:
            return chunk.web.uri, chunk.web.title
    return None, None


def _response_text(response: types.GenerateContentResponse) -> str:
    text = response.text
    if not text:
        raise GeminiGenerationError("Gemini returned no text content")
    return text


def _parse_story(response: types.GenerateContentResponse) -> MotdStory:
    """Read the structured story from a schema-constrained response."""
    parsed = response.parsed
    if isinstance(parsed, MotdStory):
        story = parsed
    else:
        try:
            story = MotdStory.model_validate(json.loads(_response_text(response)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GeminiGenerationError(f"Gemini returned an unparseable story: {exc}") from exc
    empty = [name for name in ("headline", "what", "why", "when_text", "takeaway") if not getattr(story, name).strip()]
    if empty:
        raise GeminiGenerationError(f"Gemini story is missing fields: {', '.join(empty)}")
    return story


def _call_structured(client: genai.Client, model: str, prompt: str) -> MotdStory:
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MotdStory,
        ),
    )
    return _parse_story(response)


def _generate_sync(api_key: str, theme_prompt: str, *, grounded: bool, model: str) -> tuple[MotdStory, str | None]:
    client = genai.Client(api_key=api_key)

    if not grounded:
        story = _call_structured(client, model, theme_prompt + "\n\n" + _KNOWLEDGE_SUFFIX + _STRUCTURE_INSTRUCTIONS)
        return story, None

    research = client.models.generate_content(
        model=model,
        contents=theme_prompt + "\n\n" + _GROUNDED_RESEARCH_SUFFIX,
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
    )
    source_url, source_title = _first_grounding_source(research)
    story = _call_structured(
        client,
        model,
        "Extract the required fields from this story summary.\n\n"
        + _STRUCTURE_INSTRUCTIONS
        + "\n\nStory summary:\n"
        + _response_text(research),
    )
    if story.source_title is None and source_title:
        story = story.model_copy(update={"source_title": source_title})
    return story, source_url


async def generate_motd_story(
    api_key: str,
    theme_prompt: str,
    *,
    grounded: bool,
    model: str = DEFAULT_TEXT_MODEL,
) -> tuple[MotdStory, str | None]:
    """Generate one structured MOTD story.

    Returns the story plus the grounded source URL (``None`` in knowledge
    mode or when grounding surfaced no web source — callers then skip the
    QR part). The SDK is synchronous, so the call runs in a worker thread.
    """
    return await asyncio.to_thread(_generate_sync, api_key, theme_prompt, grounded=grounded, model=model)
