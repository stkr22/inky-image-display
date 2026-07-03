"""Tests for the MOTD screen renderer.

The hard invariant is exact output dimensions — the controller rejects any
image whose size differs from the panel's, so every render path must hit
the target exactly at all supported panel sizes and orientations.
"""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from inky_image_display_api.services.motd_renderer import render_part, render_text_screen
from inky_image_display_shared.models import MotdMessage
from PIL import Image

PANEL_DIMS = [(640, 400), (800, 480), (1600, 1200), (400, 640), (480, 800), (1200, 1600)]


def _message(**overrides: object) -> MotdMessage:
    fields: dict = {
        "config_id": uuid4(),
        "headline": "Village builds its own bridge",
        "what": "A village crowdfunded and built a footbridge.",
        "why": "It reconnects two communities split by a river.",
        "when_text": "Last week",
        "takeaway": "Small groups can fix big gaps.",
        "source_url": "https://news.example/bridge",
        "source_title": "Example News",
    }
    fields.update(overrides)
    return MotdMessage(**fields)


def _open(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


@pytest.mark.parametrize(("width", "height"), PANEL_DIMS)
@pytest.mark.parametrize("part", ["what", "why", "when", "takeaway", "qr", "what+when"])
def test_every_part_renders_exact_dimensions(part: str, width: int, height: int) -> None:
    data = render_part(part, _message(), None, width, height)
    assert data is not None
    image = _open(data)
    assert image.size == (width, height)
    assert image.format == "JPEG"


def test_image_part_renders_exact_dimensions() -> None:
    source = BytesIO()
    Image.new("RGB", (1024, 768), "#3355aa").save(source, format="JPEG")
    data = render_part("image", _message(), source.getvalue(), 800, 480)
    assert data is not None
    assert _open(data).size == (800, 480)


def test_image_part_without_bytes_returns_none() -> None:
    assert render_part("image", _message(), None, 800, 480) is None


def test_qr_without_source_url_returns_none() -> None:
    assert render_part("qr", _message(source_url=None), None, 800, 480) is None


def test_text_part_with_empty_body_returns_none() -> None:
    assert render_part("takeaway", _message(takeaway=None), None, 800, 480) is None
    assert render_part("what+takeaway", _message(takeaway=None), None, 800, 480) is None


def test_screen_is_not_blank() -> None:
    data = render_part("what", _message(), None, 800, 480)
    assert data is not None
    image = _open(data).convert("L")
    darkest = min(image.tobytes())
    assert darkest < 100


def test_very_long_body_still_fits() -> None:
    long_body = " ".join(["This sentence pads the story body far beyond a comfortable fit."] * 40)
    data = render_text_screen([("WHAT HAPPENED?", long_body)], 640, 400)
    assert _open(data).size == (640, 400)


def test_unbreakable_word_does_not_hang() -> None:
    data = render_text_screen([("WHAT HAPPENED?", "a" * 500)], 640, 400)
    assert _open(data).size == (640, 400)
