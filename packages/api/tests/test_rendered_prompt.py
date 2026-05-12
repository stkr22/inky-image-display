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


def test_render_appends_portrait_orientation_hint() -> None:
    out = _prompt(is_portrait=True).render("X")
    assert out.endswith("Portrait orientation.")


def test_render_appends_landscape_orientation_hint() -> None:
    out = _prompt(is_portrait=False).render("X")
    assert out.endswith("Landscape orientation.")


def test_aspect_ratio_matches_orientation() -> None:
    assert _prompt(is_portrait=True).aspect_ratio == "3:4"
    assert _prompt(is_portrait=False).aspect_ratio == "4:3"
