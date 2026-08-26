"""Migrations 0029/0030 must retire the old models without overriding operator choices.

The retired model still answers for older API keys, so this only becomes
visible when a key is rotated or a new deployment is stood up — which is
exactly when nobody is looking for it. The guard matters as much as the fix:
a model an operator typed in the UI must survive.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import inky_image_display_api
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from inky_image_display_api.database import create_tables
from inky_image_display_shared.ai import DEFAULT_MODEL, DEFAULT_TEXT_MODEL
from inky_image_display_shared.models import DisplayJob, PromptPreset
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType

_RETIRED = "gemini-2.5-flash"
_REPLACEMENT = "gemini-3.6-flash"


@pytest.fixture
async def seeded_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    monkeypatch.setenv("API_DATABASE_PATH", db_path_str)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    await create_tables(engine)
    try:
        yield engine
    finally:
        await engine.dispose()
        db_path.unlink(missing_ok=True)


async def _insert_job(engine: AsyncEngine, name: str, model: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO display_jobs (id, name, job_type, content_prompt, source_mode, "
                "text_model_name, is_active, schedule_timezone, created_at, updated_at) "
                "VALUES (:id, :n, 'motd', 'prompt', 'grounded', :m, 1, 'UTC', :now, :now)"
            ),
            {"id": str(uuid.uuid4()), "n": name, "m": model, "now": now},
        )


async def _models(engine: AsyncEngine) -> dict[str, str]:
    async with engine.begin() as conn:
        rows = (await conn.execute(sa.text("SELECT name, text_model_name FROM display_jobs"))).fetchall()
    return {row[0]: row[1] for row in rows}


async def test_retired_default_is_repointed_and_operator_choice_is_kept(seeded_engine: AsyncEngine) -> None:
    await _insert_job(seeded_engine, "on-old-default", _RETIRED)
    await _insert_job(seeded_engine, "operator-picked", "gemini-3-pro-preview")

    migration = _load_migration("0029_retire_gemini_2_5_flash")
    async with seeded_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _run(sync_conn, migration))

    models = await _models(seeded_engine)
    assert models["on-old-default"] == _REPLACEMENT
    # A deliberate choice is left alone even though it is not the new default.
    assert models["operator-picked"] == "gemini-3-pro-preview"


async def test_rerun_is_idempotent(seeded_engine: AsyncEngine) -> None:
    await _insert_job(seeded_engine, "job", _RETIRED)
    migration = _load_migration("0029_retire_gemini_2_5_flash")
    for _ in range(2):
        async with seeded_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _run(sync_conn, migration))
    assert (await _models(seeded_engine))["job"] == _REPLACEMENT


async def test_new_jobs_default_to_the_replacement() -> None:
    # The model default and the shared fallback must not drift apart, or a job
    # created without an explicit model would still land on the retired one.
    assert DisplayJob(name="x", content_prompt="y").text_model_name == _REPLACEMENT
    assert DEFAULT_TEXT_MODEL == _REPLACEMENT


def _load_migration(stem: str) -> ModuleType:
    api_root = Path(inky_image_display_api.__file__).parent
    spec = importlib.util.spec_from_file_location(stem, api_root / "_migrations" / "versions" / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(sync_conn: sa.engine.Connection, migration: ModuleType) -> None:
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        migration.upgrade()


async def test_image_preset_on_the_retiring_default_is_repointed(seeded_engine: AsyncEngine) -> None:
    """0030 moves presets off gemini-2.5-flash-image but spares chosen models."""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with seeded_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE prompt_presets SET model_name = 'gemini-2.5-flash-image', updated_at = :now"),
            {"now": now},
        )
        # One preset an operator pinned deliberately.
        await conn.execute(sa.text("UPDATE prompt_presets SET model_name = 'imagen-4' WHERE name = 'bookshelf_hero'"))

    migration = _load_migration("0030_retire_gemini_2_5_flash_image")
    async with seeded_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _run(sync_conn, migration))

    async with seeded_engine.begin() as conn:
        rows = (await conn.execute(sa.text("SELECT name, model_name FROM prompt_presets"))).fetchall()
    models = {row[0]: row[1] for row in rows}
    assert models["bookshelf_hero"] == "imagen-4"
    assert all(m == "gemini-3.1-flash-image" for n, m in models.items() if n != "bookshelf_hero")


async def test_new_presets_default_to_the_replacement_image_model() -> None:
    block = uuid.uuid4()
    preset = PromptPreset(
        name="x",
        style_block_id=block,
        palette_block_id=block,
        legibility_block_id=block,
        composition_block_id=block,
        background_block_id=block,
    )
    assert preset.model_name == DEFAULT_MODEL == "gemini-3.1-flash-image"
