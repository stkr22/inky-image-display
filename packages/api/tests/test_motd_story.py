"""Tests for the MOTD story generation wrapper (mocked Gemini client)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from inky_image_display_shared.ai import GeminiGenerationError, MotdStory, generate_motd_story

STORY_FIELDS: dict[str, Any] = {
    "headline": "Village builds its own bridge",
    "what": "A village crowdfunded and built a footbridge.",
    "why": "It reconnects two communities split by a river.",
    "when_text": "Last week",
    "takeaway": "Small groups can fix big gaps.",
    "image_subject": "A wooden footbridge over a calm river at sunrise.",
    "source_title": None,
}


def _structured_response(parsed: object = None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.parsed = parsed
    response.text = text
    response.candidates = []
    return response


def _grounded_response(text: str, chunks: list[object]) -> MagicMock:
    response = MagicMock()
    response.parsed = None
    response.text = text
    metadata = SimpleNamespace(grounding_chunks=chunks)
    response.candidates = [SimpleNamespace(grounding_metadata=metadata)]
    return response


def _web_chunk(uri: str | None, title: str | None) -> SimpleNamespace:
    return SimpleNamespace(web=SimpleNamespace(uri=uri, title=title))


@pytest.mark.asyncio
async def test_knowledge_mode_uses_parsed_story() -> None:
    story = MotdStory(**STORY_FIELDS)
    client = MagicMock()
    client.models.generate_content.return_value = _structured_response(parsed=story)

    with patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client):
        result, source_url = await generate_motd_story("key", "themes", grounded=False)

    assert result == story
    assert source_url is None
    assert client.models.generate_content.call_count == 1
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_knowledge_mode_falls_back_to_json_text() -> None:
    client = MagicMock()
    client.models.generate_content.return_value = _structured_response(text=json.dumps(STORY_FIELDS))

    with patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client):
        result, _ = await generate_motd_story("key", "themes", grounded=False)

    assert result.headline == STORY_FIELDS["headline"]


@pytest.mark.asyncio
async def test_unparseable_story_raises() -> None:
    client = MagicMock()
    client.models.generate_content.return_value = _structured_response(text="not json {")

    with (
        patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client),
        pytest.raises(GeminiGenerationError, match="unparseable"),
    ):
        await generate_motd_story("key", "themes", grounded=False)


@pytest.mark.asyncio
async def test_blank_required_field_raises() -> None:
    story = MotdStory(**{**STORY_FIELDS, "takeaway": "  "})
    client = MagicMock()
    client.models.generate_content.return_value = _structured_response(parsed=story)

    with (
        patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client),
        pytest.raises(GeminiGenerationError, match="takeaway"),
    ):
        await generate_motd_story("key", "themes", grounded=False)


@pytest.mark.asyncio
async def test_grounded_mode_extracts_source_from_metadata() -> None:
    research = _grounded_response(
        "A village built a footbridge last week.",
        [_web_chunk("https://news.example/bridge", "Example News")],
    )
    structured = _structured_response(parsed=MotdStory(**STORY_FIELDS))
    client = MagicMock()
    client.models.generate_content.side_effect = [research, structured]

    with patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client):
        result, source_url = await generate_motd_story("key", "themes", grounded=True)

    assert source_url == "https://news.example/bridge"
    # Title from the grounding chunk backfills a missing source_title.
    assert result.source_title == "Example News"
    assert client.models.generate_content.call_count == 2
    research_config = client.models.generate_content.call_args_list[0].kwargs["config"]
    assert research_config.tools is not None


@pytest.mark.asyncio
async def test_grounded_mode_without_web_chunks_returns_no_url() -> None:
    research = _grounded_response("A story without sources.", [])
    structured = _structured_response(parsed=MotdStory(**STORY_FIELDS))
    client = MagicMock()
    client.models.generate_content.side_effect = [research, structured]

    with patch("inky_image_display_shared.ai.gemini_text.genai.Client", return_value=client):
        result, source_url = await generate_motd_story("key", "themes", grounded=True)

    assert source_url is None
    assert result.source_title is None
