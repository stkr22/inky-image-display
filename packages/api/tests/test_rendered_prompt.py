"""Unit tests for the shared RenderedPrompt block composition."""

from __future__ import annotations

from inky_image_display_shared.ai import RenderedPrompt


def _prompt(*, is_portrait: bool = True) -> RenderedPrompt:
    return RenderedPrompt(
        style="STYLE_TEXT",
        palette="PALETTE_TEXT",
        legibility="LEG_TEXT",
        composition="COMP about {subject}",
        background="BG_TEXT",
        is_portrait=is_portrait,
    )


def test_render_substitutes_subject_and_orders_blocks() -> None:
    out = _prompt().render("Ada Lovelace")
    # Subject is inserted both at the top and inside the composition block.
    assert "Bold illustrated portrait of Ada Lovelace." in out
    assert "COMP about Ada Lovelace" in out
    # All blocks make it into the final prompt.
    for needle in ("STYLE_TEXT", "PALETTE_TEXT", "LEG_TEXT", "BG_TEXT"):
        assert needle in out


def test_orientation_drives_hint_and_aspect_ratio() -> None:
    portrait = _prompt(is_portrait=True)
    assert portrait.render("X").endswith("Portrait orientation.")
    assert portrait.aspect_ratio == "3:4"

    landscape = _prompt(is_portrait=False)
    assert landscape.render("X").endswith("Landscape orientation.")
    assert landscape.aspect_ratio == "4:3"
