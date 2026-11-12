"""Migrations 0028/0032 must create the bookshelf job table and seed its presets.

The prompts are the outcome of a design pass against real panels, so the point
of these tests is that a fresh database comes up with working presets rather
than an operator having to retype them — and that re-running the migration on a
database where someone has since edited a block leaves the edit alone.
0032 borrows the shelf preset's shared blocks for the bookcase preset, so it
must skip the preset rather than half-build it when those are gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from .conftest import alembic_downgrade, alembic_upgrade, load_migration

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from sqlalchemy.ext.asyncio import AsyncEngine


async def test_job_table_created(seeded_engine: AsyncEngine) -> None:
    async with seeded_engine.begin() as conn:
        rows = (await conn.execute(sa.text("PRAGMA table_info(calibre_sync_jobs)"))).fetchall()
    columns = {row[1] for row in rows}
    assert {"mode", "tags", "books_per_shelf", "verify_spines", "max_attempts"} <= columns
    assert not {"series", "min_rating"} & columns
    assert {"shelf_rows", "avoid_repeats"} <= columns


async def test_both_presets_seeded_with_their_own_blocks(seeded_engine: AsyncEngine) -> None:
    async with seeded_engine.begin() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT p.name, p.is_default, s.name, c.name, b.name "
                    "FROM prompt_presets p "
                    "JOIN prompt_blocks s ON s.id = p.style_block_id "
                    "JOIN prompt_blocks c ON c.id = p.composition_block_id "
                    "JOIN prompt_blocks b ON b.id = p.background_block_id "
                    "WHERE p.name LIKE 'bookshelf%' ORDER BY p.name"
                )
            )
        ).fetchall()
    assert [r[0] for r in rows] == ["bookshelf_bookcase", "bookshelf_hero", "bookshelf_shelf"]
    # Neither may displace the library default used by on-demand generation.
    assert not any(r[1] for r in rows)
    assert (rows[0][2], rows[0][3], rows[0][4]) == ("bookshelf_painterly", "bookcase_rows", "bookcase_oak_tall")
    assert (rows[1][2], rows[1][3], rows[1][4]) == ("book_cover_as_is", "book_hero_object", "book_hero_atmosphere")
    assert (rows[2][2], rows[2][3], rows[2][4]) == (
        "bookshelf_painterly",
        "bookshelf_spines",
        "bookshelf_oak_case",
    )


async def test_composition_blocks_carry_the_subject_placeholder(seeded_engine: AsyncEngine) -> None:
    # Without {subject} the book list never reaches the prompt and every shelf
    # would be generated from the styling alone.
    async with seeded_engine.begin() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT name, text FROM prompt_blocks "
                    "WHERE name IN ('bookshelf_spines', 'book_hero_object', 'bookcase_rows')"
                )
            )
        ).fetchall()
    assert len(rows) == 3
    assert all("{subject}" in row[1] for row in rows)


async def test_seed_is_idempotent(seeded_engine: AsyncEngine) -> None:
    migration = load_migration("0028_add_calibre_sync_jobs")
    async with seeded_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _seed_only(sync_conn, migration))
    async with seeded_engine.begin() as conn:
        presets = (
            await conn.execute(sa.text("SELECT COUNT(*) FROM prompt_presets WHERE name LIKE 'bookshelf%'"))
        ).scalar_one()
        blocks = (
            await conn.execute(sa.text("SELECT COUNT(*) FROM prompt_blocks WHERE name LIKE 'book%'"))
        ).scalar_one()
    assert presets == 3
    assert blocks == 10


async def test_operator_edited_block_is_preserved(seeded_engine: AsyncEngine) -> None:
    """A block edited in the UI must survive a re-run untouched."""
    migration = load_migration("0028_add_calibre_sync_jobs")
    custom = "MY HAND-TUNED SHELF — keep this."
    async with seeded_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE prompt_blocks SET text = :t WHERE name = 'bookshelf_painterly'"),
            {"t": custom},
        )
        await conn.run_sync(lambda sync_conn: _seed_only(sync_conn, migration))
    async with seeded_engine.begin() as conn:
        text = (
            await conn.execute(sa.text("SELECT text FROM prompt_blocks WHERE name = 'bookshelf_painterly'"))
        ).scalar_one()
    assert text == custom


def _seed_only(sync_conn: sa.engine.Connection, migration: ModuleType) -> None:
    """Re-run just the seeding half; ``upgrade()`` would recreate the table."""
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        migration._seed_prompts(sync_conn)


def test_bookcase_preset_skipped_when_shared_blocks_were_deleted(migrated_db: Path) -> None:
    """0032 must not build a half-wired preset if an operator removed the shared blocks."""
    # Step back to before 0032 and remove what it would borrow from the shelf preset.
    alembic_downgrade(migrated_db, "0031")
    engine = sa.create_engine(f"sqlite:///{migrated_db}")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM prompt_presets WHERE name LIKE 'bookshelf%'"))
            conn.execute(
                sa.text(
                    "DELETE FROM prompt_blocks WHERE name IN "
                    "('bookshelf_painterly', 'bookshelf_palette', 'bookshelf_legibility', "
                    "'bookcase_rows', 'bookcase_oak_tall')"
                )
            )
        alembic_upgrade(migrated_db, "0032")
        with engine.connect() as conn:
            preset = conn.execute(sa.text("SELECT 1 FROM prompt_presets WHERE name = 'bookshelf_bookcase'")).first()
            blocks = conn.execute(
                sa.text("SELECT name FROM prompt_blocks WHERE name IN ('bookcase_rows', 'bookcase_oak_tall')")
            ).fetchall()
    finally:
        engine.dispose()
    assert preset is None
    # The mode's own blocks are still seeded, so recreating the shared ones is enough to wire a preset by hand.
    assert sorted(row[0] for row in blocks) == ["bookcase_oak_tall", "bookcase_rows"]
