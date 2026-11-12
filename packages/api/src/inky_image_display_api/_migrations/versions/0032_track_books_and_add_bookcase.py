"""Record which books each image holds; add the tall bookcase mode.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-12

Until now an image only mentioned its books in free text, so nothing could say
"this book is already on a wall". ``image_books`` makes that a queryable fact,
and ``calibre_sync_jobs.avoid_repeats`` uses it to keep a book from appearing
twice at once, whether on two shelves or as a shelf and a hero.

``shelf_rows`` belongs to the new ``bookcase`` mode: a portrait panel holding
several stacked shelves, where ``shelf`` is a single landscape row. The mode
gets its own composition and background blocks and one preset, seeded here so
it works out of the box. The style, palette and legibility blocks are shared
with the existing shelf preset; if an operator has deleted them, the preset is
skipped rather than half-built.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_IMAGE_MODEL = "gemini-3-pro-image"

# {subject} lists the books grouped per shelf, top shelf first; the sync
# service builds it. The shelf count is stated there rather than here so one
# block serves any number of rows.
_CASE_COMPOSITION = (
    "A tall wooden bookcase seen straight on, filling a portrait frame from top to bottom and side "
    "to side. It has several shelves stacked one above another, and each shelf holds one row of "
    "books standing upright side by side with their spines facing the viewer. Show EXACTLY the "
    "shelves listed below, no more and no fewer, and put on each shelf EXACTLY the books listed "
    "for it, in that order from left to right. Every spine carries its title and author as clearly "
    "legible printed text, spelled EXACTLY as given:\n{subject}\n"
    "Vary spine width, height and colour so it reads as a real collection, with the books on one "
    "shelf sharing a common baseline. Text runs vertically along each spine. Do not paint any "
    "numbers on the books. Spine lettering is LARGE and BOLD, in strong contrast against the "
    "spine colour so it reads from across a room."
)
_CASE_BACKGROUND = (
    "The bookcase is warm light oak with visible grain, lit by warm lamplight from one side. It "
    "has real depth: the shelf boards show their thickness and the interior recedes into soft "
    "shadow behind the books, which cast gentle shadows into the gaps between spines. Keep the "
    "shelf boards slim and the frame minimal so the books, not the furniture, take up the image. "
    "No objects stand on or between the shelves other than the books."
)

_BLOCKS = [
    ("composition", "bookcase_rows", _CASE_COMPOSITION),
    ("background", "bookcase_oak_tall", _CASE_BACKGROUND),
]
_SHARED_BLOCKS = {
    "style_block_id": "bookshelf_painterly",
    "palette_block_id": "bookshelf_palette",
    "legibility_block_id": "bookshelf_legibility",
}
_PRESET_NAME = "bookshelf_bookcase"

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


def _block_id(bind: sa.engine.Connection, name: str) -> uuid.UUID | None:
    found = bind.execute(sa.text("SELECT id FROM prompt_blocks WHERE name = :n"), {"n": name}).fetchone()
    if found is None:
        return None
    value = found[0]
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(bytes=value) if isinstance(value, bytes) else uuid.UUID(str(value))


def _seed_prompts(bind: sa.engine.Connection) -> None:
    """Insert the bookcase blocks and preset, skipping anything already there."""
    now = datetime.now(UTC).replace(tzinfo=None)
    ids: dict[str, uuid.UUID] = {}
    for kind, name, text in _BLOCKS:
        existing = _block_id(bind, name)
        if existing is not None:
            ids[name] = existing
            continue
        ids[name] = uuid.uuid4()
        op.bulk_insert(
            _BLOCKS_TBL,
            [
                {
                    "id": ids[name],
                    "kind": kind,
                    "name": name,
                    "text": text,
                    "is_default": False,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    shared = {column: _block_id(bind, name) for column, name in _SHARED_BLOCKS.items()}
    if any(value is None for value in shared.values()):
        return
    if bind.execute(sa.text("SELECT 1 FROM prompt_presets WHERE name = :n"), {"n": _PRESET_NAME}).fetchone():
        return
    op.bulk_insert(
        _PRESETS_TBL,
        [
            {
                "id": uuid.uuid4(),
                **shared,
                "name": _PRESET_NAME,
                "composition_block_id": ids["bookcase_rows"],
                "background_block_id": ids["bookcase_oak_tall"],
                "model_name": _IMAGE_MODEL,
                "is_default": False,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def upgrade() -> None:
    """Create the image/book link table, add the job columns, seed the preset."""
    op.create_table(
        "image_books",
        sa.Column("image_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("image_id", "position"),
    )
    op.create_index(op.f("ix_image_books_book_id"), "image_books", ["book_id"])

    with op.batch_alter_table("calibre_sync_jobs") as batch:
        batch.add_column(sa.Column("avoid_repeats", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("shelf_rows", sa.Integer(), nullable=False, server_default="3"))

    _seed_prompts(op.get_bind())


def downgrade() -> None:
    """Drop the link table and job columns; seeded prompts stay for presets using them."""
    with op.batch_alter_table("calibre_sync_jobs") as batch:
        batch.drop_column("shelf_rows")
        batch.drop_column("avoid_repeats")
    op.drop_index(op.f("ix_image_books_book_id"), table_name="image_books")
    op.drop_table("image_books")
