"""Migration 0028 must create the bookshelf job table and seed its two presets.

The prompts are the outcome of a design pass against real panels, so the point
of these tests is that a fresh database comes up with working presets rather
than an operator having to retype them — and that re-running the migration on a
database where someone has since edited a block leaves the edit alone.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import inky_image_display_api
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from inky_image_display_api.database import create_tables
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType


@pytest.fixture
async def seeded_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    """Fresh SQLite DB with all migrations applied — exercises real seeding."""
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    # env.py honours this and would otherwise migrate the shared dev database.
    monkeypatch.setenv("API_DATABASE_PATH", db_path_str)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    await create_tables(engine)
    try:
        yield engine
    finally:
        await engine.dispose()
        db_path.unlink(missing_ok=True)


async def test_job_table_created(seeded_engine: AsyncEngine) -> None:
    async with seeded_engine.begin() as conn:
        rows = (await conn.execute(sa.text("PRAGMA table_info(calibre_sync_jobs)"))).fetchall()
    columns = {row[1] for row in rows}
    assert {"mode", "tags", "min_rating", "books_per_shelf", "verify_spines", "max_attempts"} <= columns


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
    assert [r[0] for r in rows] == ["bookshelf_hero", "bookshelf_shelf"]
    # Neither may displace the library default used by on-demand generation.
    assert not any(r[1] for r in rows)
    assert (rows[0][2], rows[0][3], rows[0][4]) == ("book_cover_as_is", "book_hero_object", "book_hero_atmosphere")
    assert (rows[1][2], rows[1][3], rows[1][4]) == (
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
                sa.text("SELECT name, text FROM prompt_blocks WHERE name IN ('bookshelf_spines', 'book_hero_object')")
            )
        ).fetchall()
    assert len(rows) == 2
    assert all("{subject}" in row[1] for row in rows)


async def test_seed_is_idempotent(seeded_engine: AsyncEngine) -> None:
    migration = _load_migration("0028_add_calibre_sync_jobs")
    async with seeded_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _seed_only(sync_conn, migration))
    async with seeded_engine.begin() as conn:
        presets = (
            await conn.execute(sa.text("SELECT COUNT(*) FROM prompt_presets WHERE name LIKE 'bookshelf%'"))
        ).scalar_one()
        blocks = (
            await conn.execute(sa.text("SELECT COUNT(*) FROM prompt_blocks WHERE name LIKE 'book%'"))
        ).scalar_one()
    assert presets == 2
    assert blocks == 8


async def test_operator_edited_block_is_preserved(seeded_engine: AsyncEngine) -> None:
    """A block edited in the UI must survive a re-run untouched."""
    migration = _load_migration("0028_add_calibre_sync_jobs")
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


def _load_migration(stem: str) -> ModuleType:
    """Import a migration module by file stem so its helpers can run in isolation."""
    api_root = Path(inky_image_display_api.__file__).parent
    spec = importlib.util.spec_from_file_location(stem, api_root / "_migrations" / "versions" / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_only(sync_conn: sa.engine.Connection, migration: ModuleType) -> None:
    """Re-run just the seeding half; ``upgrade()`` would recreate the table."""
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        migration._seed_prompts(sync_conn)
