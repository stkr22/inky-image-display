"""Read printed text back out of a generated image.

Image models render book spines convincingly but not reliably: a title loses a
letter, an author migrates to the neighbouring book, or a seventh book appears
on a six-book shelf. None of that is visible from the generation call, and all
of it is obvious to a reader across the room.

Since the exact strings that *should* appear are known before generating, the
image can be handed back to the model to be transcribed and the result compared
against them. The transcription prompt insists on copying misspellings verbatim
— a model asked to read "Ufo der geheimen Weelt" will happily correct it to
"Welt" from world knowledge, which would defeat the entire check.
"""

from __future__ import annotations

import asyncio
import json
import re

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from inky_image_display_shared.ai.gemini import GeminiGenerationError

# Vision-capable text model: transcription is far cheaper than generation and
# does not need the image model that produced the picture. Pinned rather than
# an alias so a model swap cannot quietly change what passes verification.
DEFAULT_VISION_MODEL = "gemini-3.6-flash"

_TRANSCRIBE_PROMPT = """\
Read every book spine in this image, from left to right. For each spine, \
transcribe the title and the author EXACTLY as printed, character for \
character, including any misspellings, duplicated words or missing letters. \
Do NOT correct anything, do NOT tidy the wording, and do NOT use outside \
knowledge of these books — report only the literal glyphs you can see. If a \
spine has no visible author, return an empty string for it. Report every book \
you can see, even if some appear blank."""

# The model swaps freely between hyphen, en dash and em dash.
_DASHES = re.compile("[\u2010-\u2015]")
_WHITESPACE = re.compile(r"\s+")


class SpineReading(BaseModel):
    """One spine as transcribed from a generated image."""

    title: str
    author: str


class ShelfReading(BaseModel):
    """Every spine the model could read, left to right."""

    spines: list[SpineReading]


def normalize_printed(text: str) -> str:
    """Fold typographic variation that does not matter to a reader.

    The model swaps hyphens for en-dashes and varies capitalisation freely
    between runs. Treating those as defects would regenerate perfectly good
    shelves, so only the letters are compared.
    """
    return _WHITESPACE.sub(" ", _DASHES.sub("-", text)).strip().casefold()


def spines_match(expected: list[tuple[str, str]], actual: list[SpineReading]) -> bool:
    """Report whether a transcription carries exactly the requested books, in order.

    Count is part of the check: an extra invented book is as wrong as a
    misspelt one, and is a failure mode that has actually occurred.
    """
    if len(actual) != len(expected):
        return False
    return all(
        normalize_printed(reading.title) == normalize_printed(title)
        and normalize_printed(reading.author) == normalize_printed(author)
        for reading, (title, author) in zip(actual, expected, strict=True)
    )


def _transcribe_sync(api_key: str, image: bytes, model: str) -> list[SpineReading]:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), _TRANSCRIBE_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ShelfReading,
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, ShelfReading):
        return parsed.spines
    try:
        return ShelfReading.model_validate(json.loads(response.text or "")).spines
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GeminiGenerationError(f"Gemini returned an unreadable transcription: {exc}") from exc


async def transcribe_spines(
    api_key: str,
    image: bytes,
    *,
    model: str = DEFAULT_VISION_MODEL,
) -> list[SpineReading]:
    """Transcribe every book spine visible in ``image``, left to right."""
    return await asyncio.to_thread(_transcribe_sync, api_key, image, model)
