"""Repaint the default prompt blocks for richer, dithered Spectra 6 output.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-13

The original defaults (seeded in 0004) told Gemini to pre-flatten the image:
"use only six colors", "flat color blocks", "avoid gradients/soft shading".
But our pipeline never quantizes to six colors — the Inky library dithers the
full-colour JPEG down to the panel's six primaries (Floyd-Steinberg) at
display time. So those instructions threw away the panel's own depth: a richer,
painterly source dithers into apparent tonal range and texture (the look of
Pimoroni's Van Gogh / ship demos), and the 13.3" Spectra 6 (1600x1200) holds
moderate detail well.

This migration rewrites four blocks to embrace that — painterly depth instead
of flat blocks, a palette framed as a *blacklist* of out-of-gamut hues
(magenta/purple/cyan/teal/brown… which dither to muddy speckle) rather than a
six-colour whitelist — and tweaks the two composition blocks so they name the
subject up front (the hardcoded "portrait of {subject}" opener was removed from
``RenderedPrompt.render`` in the same change) and stop reinforcing flatness.

Each update is guarded: it only touches a row whose text still matches the
original 0004 seed, so blocks an operator has already edited in the UI are left
untouched. ``downgrade`` reverses the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


# --- Original 0004 seed text (the guard: only repaint rows still matching) ---

_OLD_STYLE = (
    "High-contrast poster / screen-print aesthetic: strong clear outlines, "
    "flat color blocks, simple chunky shapes, no photorealism. "
    "Van-Gogh-inspired color energy — saturated, dramatic complementary "
    "color blocking."
)
_OLD_PALETTE = (
    "Use only six colors: black, white, bold red, bright yellow, deep royal "
    "blue, and forest green used sparingly. Avoid muddy olive, beige, "
    "brown, teal, purple, pink, or any desaturated mid-tones."
)
_OLD_LEGIBILITY = (
    "Target medium is a 6-color e-ink display. Avoid gradients, soft "
    "shading, thin lines, wispy hair, fine textures, or any detail that "
    "would be lost with a limited palette — every feature must stay "
    "legible as bold shapes."
)
_OLD_COMPOSITION_HUMANOID = (
    "Tight close-up composition: the subject fills the frame edge to "
    "edge. Head reaches near the top of the image, shoulders span the "
    "full width, no empty margins around the portrait. Behind the "
    "subject, optionally place one or two iconic objects, symbols, or "
    "motifs associated with {subject} — rendered as large bold flat "
    "shapes or simplified illustrations behind the portrait, not a wide "
    "environmental scene and not fiddly detail."
)
_OLD_COMPOSITION_SCENE = (
    "Full-frame scene composition: {subject} occupies the central focus "
    "with surrounding context filling the frame edge to edge. Compose as "
    "bold simplified shapes — large foreground forms, mid-ground "
    "supporting elements, and a flat background. No empty margins, no "
    "fiddly background clutter."
)
_OLD_BACKGROUND = (
    "Use a bold solid color (deep blue, black, bold red, or clean white) "
    "behind the subject and any background motifs for contrast. Never "
    "green as the dominant background."
)


# --- Repainted text -----------------------------------------------------------

_NEW_STYLE = (
    "Bold painterly illustration with the expressive energy of a Van Gogh oil: "
    "confident visible brushwork, impasto texture, and dramatic light-to-shadow "
    "modelling that gives every form real depth and volume. High contrast and "
    "rich, saturated colour. Build the image from strong, well-separated shapes "
    "with a clear focal subject — but do NOT flatten them: let colour shade, "
    "blend and turn across each surface. Stylised and expressive, not "
    "photorealistic — closer to a striking gallery art print than a minimal "
    "flat poster."
)
_NEW_PALETTE = (
    "Paint freely with rich, saturated, high-contrast colour and smooth tonal "
    "shading. The e-ink panel dithers everything down to its six native "
    "primaries (black, white, red, yellow, green, blue), so there is NO need to "
    "pre-flatten to those few colours — a full painterly range reproduces as "
    "depth and texture. Avoid hues the panel cannot reach, which dither into "
    "muddy speckle: magenta, purple, violet, cyan, teal, turquoise, hot pink, "
    "and brown/beige/khaki — never use these for large areas. Treat orange as a "
    "small warm accent only (it skews red). Anchor the image in clean reds, "
    "golden yellows, deep blues and rich greens, with black and white carrying "
    "the contrast."
)
_NEW_LEGIBILITY = (
    "Target medium is a high-resolution 6-colour e-ink panel that dithers "
    "smoothly, so tonal shading, surface texture and moderate detail reproduce "
    "well — keep them, don't strip them out. Build on clear, well-separated "
    "forms with crisp high-contrast edges so the subject reads instantly from "
    "across a room. Avoid only the failure modes: hair-thin lines, tiny "
    "cluttered filigree, and broad low-contrast passages of similar mid-tones "
    "that would turn to mush."
)
_NEW_COMPOSITION_HUMANOID = (
    "Tight close-up composition of {subject}: they fill the frame edge to edge, "
    "head near the top, shoulders spanning the full width, no empty margins. "
    "Behind them, optionally place one or two iconic objects, symbols or motifs "
    "associated with {subject} — rendered as large, bold, simplified shapes set "
    "behind the subject, not a wide environmental scene and not fiddly detail."
)
_NEW_COMPOSITION_SCENE = (
    "Full-frame scene composition: {subject} occupies the central focus with "
    "surrounding context filling the frame edge to edge. Compose with bold, "
    "well-separated forms — large foreground elements, supporting mid-ground, "
    "and a simpler background that still carries its own depth and atmosphere. "
    "No empty margins, no fiddly background clutter."
)
_NEW_BACKGROUND = (
    "Place the subject against a deep, high-contrast backdrop — deep blue, "
    "near-black, bold red or clean white — carrying subtle brushwork or tonal "
    "variation rather than a dead-flat fill, so it reads as atmosphere not "
    "emptiness. Keep it distinctly darker or lighter than the subject's edges so "
    "the silhouette pops. Avoid green as the dominant background, and avoid busy "
    "clutter that competes with the subject."
)


# Each tuple is: block kind, block name, original 0004 text, repainted text.
_BLOCKS: list[tuple[str, str, str, str]] = [
    ("style", "poster_screenprint", _OLD_STYLE, _NEW_STYLE),
    ("palette", "spectra_6", _OLD_PALETTE, _NEW_PALETTE),
    ("legibility", "eink_bold_shapes", _OLD_LEGIBILITY, _NEW_LEGIBILITY),
    ("composition", "humanoid_closeup", _OLD_COMPOSITION_HUMANOID, _NEW_COMPOSITION_HUMANOID),
    ("composition", "scene_full_frame", _OLD_COMPOSITION_SCENE, _NEW_COMPOSITION_SCENE),
    ("background", "bold_solid", _OLD_BACKGROUND, _NEW_BACKGROUND),
]

_UPDATE = sa.text(
    "UPDATE prompt_blocks SET text = :new, updated_at = :now WHERE kind = :kind AND name = :name AND text = :old"
)


def _repaint(pairs: list[tuple[str, str, str, str]]) -> None:
    """Apply each (kind, name, from_text, to_text) update if the row still matches."""
    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    for kind, name, from_text, to_text in pairs:
        bind.execute(
            _UPDATE,
            {"new": to_text, "now": now, "kind": kind, "name": name, "old": from_text},
        )


def upgrade() -> None:
    """Repaint the seeded default blocks (only those still at their 0004 text)."""
    _repaint(_BLOCKS)


def downgrade() -> None:
    """Restore the original 0004 text (only on rows still carrying the repaint)."""
    _repaint([(kind, name, new, old) for kind, name, old, new in _BLOCKS])
