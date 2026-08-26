"""Add Calibre bookshelf jobs and seed their two prompt presets.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-26

The bookshelf source reads a Calibre library over OPDS and generates either a
shelf of spines or a single hero cover. Both prompts decompose cleanly into the
existing five prompt-block kinds, so no new prompt machinery is needed — the
seeded blocks are editable in the operator UI like any other.

The wording below is the outcome of a design pass against real panels, so the
comments record *why* each clause is there; the two failure modes worth keeping
in mind are that warm lamplight tints the spine inscriptions amber (hurting
legibility) and that large flat brown areas dither to muddy speckle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


# --- Prompt blocks -------------------------------------------------------------

# Shared by both presets: the panel reproduces six inks, and out-of-gamut hues
# dither into speckle rather than the colour that was asked for.
_PALETTE = (
    "Avoid hues the panel cannot reach: magenta, purple, violet, cyan, teal, turquoise and hot "
    "pink. Anchor the image in clean reds, golden yellows, deep blues and rich greens, with black "
    "and white carrying the contrast. Warm oak browns are welcome in woodwork."
)
_LEGIBILITY = (
    "Target medium is a high-resolution 6-colour e-ink panel that dithers smoothly, so tonal "
    "shading and moderate detail reproduce well. Build on clear, well-separated forms with crisp "
    "high-contrast edges so the subject reads instantly from across a room. Avoid hair-thin lines, "
    "tiny cluttered filigree, and broad low-contrast passages that would turn to mush. The artwork "
    "fills the entire frame edge to edge: no paper border, no white margin, no mount or mat, and "
    "no visible print edge."
)

_SHELF_STYLE = (
    "Bold painterly oil illustration: confident visible brushwork, impasto texture and dramatic "
    "light-to-shadow modelling giving real depth and volume. High contrast, rich saturated colour."
)
# {subject} is the formatted book list; the sync service builds it.
_SHELF_COMPOSITION = (
    "A row of books standing upright side by side on one shelf of a wooden bookcase, spines facing "
    "the viewer. Each spine carries its title and author as clearly legible printed text, spelled "
    "EXACTLY as given, one book per spine:\n{subject}\n"
    "Vary spine width, height and colour so it reads as a real collection. Text runs vertically "
    "along each spine. Do not paint any numbers on the books. The books fill most of the image, "
    "their spines spanning the great majority of its height and running edge to edge across its "
    "width. Spine lettering is LARGE and BOLD, in strong contrast against the spine colour so it "
    "reads from across a room."
)
# Depth is what makes the shelf interesting; a head-on row reads as flat pattern.
_SHELF_BACKGROUND = (
    "The bookcase is warm light oak with visible grain, lit by warm lamplight from one side — "
    "honey, amber and golden tones on the lit edges falling away into deep shadow in the recesses. "
    "It has real three-dimensional depth: seen from very slightly off-centre so that one side panel "
    "and the thickness of the shelf board are visible, with the interior receding into warm shadow "
    "behind the books. The books do not sit perfectly flush — some stand further back, one leans "
    "slightly against its neighbour, one is pulled forward — and the raking light casts soft "
    "shadows into the gaps between the spines. Keep carved decoration minimal: two or three small "
    "touches at most, such as a single carved rosette or a thin brass rail."
)

# The hero deliberately has no house style: the point is that the book looks
# like the edition on the shelf, so the attached cover dictates the treatment.
_HERO_STYLE = (
    "Reproduce the cover artwork in the SAME artistic style as the attached original: match its "
    "medium, rendering, level of realism, colour treatment and typographic character. Do NOT "
    "restyle it as a woodcut, art-deco poster, impressionist painting or any other house style. It "
    "should look like this book as actually published, just redrawn cleanly rather than copied "
    "pixel for pixel."
)
_HERO_COMPOSITION = (
    "The book is a real physical hardback standing upright on a plain surface, seen very slightly "
    "from one side so its thickness, spine edge and page block are visible, with a soft cast shadow "
    "anchoring it. It stands clearly and unmistakably as a book, sharply in focus, occupying "
    "roughly half the image height and centred. Its cover is the cover of {subject}, carrying that "
    "title and author as clearly legible printed text, spelled EXACTLY as given."
)
# Atmosphere without a scene: a plain backdrop reads as product photography,
# a continued scene swallows the book.
_HERO_BACKGROUND = (
    "Behind the book, a dark atmospheric space — NOT a studio backdrop and NOT a plain wall. Strong "
    "directional light rakes in from one side; the light and colour of the cover's own world spills "
    "out onto the surroundings as glow, haze and cast shadow, as if the cover were lit from within "
    "and bleeding its atmosphere into the room. Deep shadows, visible haze, dramatic chiaroscuro "
    "contrast. No objects, no characters, no scene — only light, shadow and atmosphere. The book "
    "stays sharply lit, crisp and dominant against it."
)

_IMAGE_MODEL = "gemini-3-pro-image"

# Each tuple is: block kind, block name, block text.
_BLOCKS: list[tuple[str, str, str]] = [
    ("style", "bookshelf_painterly", _SHELF_STYLE),
    ("composition", "bookshelf_spines", _SHELF_COMPOSITION),
    ("background", "bookshelf_oak_case", _SHELF_BACKGROUND),
    ("palette", "bookshelf_palette", _PALETTE),
    ("legibility", "bookshelf_legibility", _LEGIBILITY),
    ("style", "book_cover_as_is", _HERO_STYLE),
    ("composition", "book_hero_object", _HERO_COMPOSITION),
    ("background", "book_hero_atmosphere", _HERO_BACKGROUND),
]

_PRESETS: list[tuple[str, dict[str, str]]] = [
    (
        "bookshelf_shelf",
        {
            "style_block_id": "bookshelf_painterly",
            "composition_block_id": "bookshelf_spines",
            "background_block_id": "bookshelf_oak_case",
            "palette_block_id": "bookshelf_palette",
            "legibility_block_id": "bookshelf_legibility",
        },
    ),
    (
        "bookshelf_hero",
        {
            "style_block_id": "book_cover_as_is",
            "composition_block_id": "book_hero_object",
            "background_block_id": "book_hero_atmosphere",
            "palette_block_id": "bookshelf_palette",
            "legibility_block_id": "bookshelf_legibility",
        },
    ),
]

_BLOCKS_TBL = sa.Table(
    "prompt_blocks",
    sa.MetaData(),
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("kind", sa.String()),
    sa.Column("name", sa.String()),
    sa.Column("text", sa.String()),
    sa.Column("is_default", sa.Boolean()),
    sa.Column("created_at", sa.DateTime()),
    sa.Column("updated_at", sa.DateTime()),
)

_PRESETS_TBL = sa.Table(
    "prompt_presets",
    sa.MetaData(),
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("name", sa.String()),
    sa.Column("style_block_id", sa.Uuid()),
    sa.Column("palette_block_id", sa.Uuid()),
    sa.Column("legibility_block_id", sa.Uuid()),
    sa.Column("composition_block_id", sa.Uuid()),
    sa.Column("background_block_id", sa.Uuid()),
    sa.Column("model_name", sa.String()),
    sa.Column("is_default", sa.Boolean()),
    sa.Column("created_at", sa.DateTime()),
    sa.Column("updated_at", sa.DateTime()),
)


def _coerce_uuid(value: object) -> uuid.UUID:
    """Parse a UUID column value regardless of stored string format."""
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes):
        return uuid.UUID(bytes=value)
    return uuid.UUID(str(value))


def _seed_prompts(bind: sa.engine.Connection) -> None:
    """Insert the bookshelf blocks and presets, skipping anything already there."""
    now = datetime.now(UTC).replace(tzinfo=None)
    block_ids: dict[str, uuid.UUID] = {}

    for kind, name, text in _BLOCKS:
        found = bind.execute(sa.text("SELECT id FROM prompt_blocks WHERE name = :n"), {"n": name}).fetchone()
        if found is not None:
            block_ids[name] = _coerce_uuid(found[0])
            continue
        block_id = uuid.uuid4()
        block_ids[name] = block_id
        op.bulk_insert(
            _BLOCKS_TBL,
            [
                {
                    "id": block_id,
                    "kind": kind,
                    "name": name,
                    "text": text,
                    # These are bookshelf-specific; nothing else should fall
                    # back to them.
                    "is_default": False,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    for preset_name, mapping in _PRESETS:
        row = bind.execute(sa.text("SELECT 1 FROM prompt_presets WHERE name = :n"), {"n": preset_name}).fetchone()
        if row is not None:
            continue
        op.bulk_insert(
            _PRESETS_TBL,
            [
                {
                    "id": uuid.uuid4(),
                    "name": preset_name,
                    **{column: block_ids[block_name] for column, block_name in mapping.items()},
                    "model_name": _IMAGE_MODEL,
                    "is_default": False,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )


def upgrade() -> None:
    """Create the job table and seed the bookshelf prompts."""
    op.create_table(
        "calibre_sync_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mode", sa.String(), nullable=False, server_default="shelf"),
        sa.Column("target_device_profile_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_preset_id", sa.Uuid(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("series", sa.JSON(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("min_rating", sa.Integer(), nullable=True),
        sa.Column("books_per_shelf", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("images_per_run", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("verify_spines", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("schedule_cron", sa.String(), nullable=True),
        sa.Column("schedule_timezone", sa.String(), nullable=False, server_default="UTC"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("run_requested_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["target_device_profile_id"], ["device_profiles.id"]),
        sa.ForeignKeyConstraint(["prompt_preset_id"], ["prompt_presets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_calibre_sync_jobs_name"), "calibre_sync_jobs", ["name"], unique=True)

    _seed_prompts(op.get_bind())


def downgrade() -> None:
    """Drop the job table; seeded prompts are left for any preset still using them."""
    op.drop_index(op.f("ix_calibre_sync_jobs_name"), table_name="calibre_sync_jobs")
    op.drop_table("calibre_sync_jobs")
