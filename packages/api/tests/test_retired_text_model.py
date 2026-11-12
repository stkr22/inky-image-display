"""Migrations 0029/0030 must retire the old models without overriding operator choices.

The retired model still answers for older API keys, so this only becomes
visible when a key is rotated or a new deployment is stood up — which is
exactly when nobody is looking for it. The guard matters as much as the fix:
a model an operator typed in the UI must survive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from inky_image_display_shared.ai import DEFAULT_MODEL, DEFAULT_TEXT_MODEL
from inky_image_display_shared.models import DisplayJob, PromptPreset

from .conftest import load_migration

if TYPE_CHECKING:
    from types import ModuleType

    from sqlalchemy.ext.asyncio import AsyncEngine

_RETIRED = "gemini-2.5-flash"
_REPLACEMENT = "gemini-3.6-flash"


async def _insert_job(engine: AsyncEngine, name: str, model: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO display_jobs (id, name, job_type, content_prompt, source_mode, "
                "text_model_name, is_active, schedule_timezone, created_at, updated_at) "
                "VALUES (:id, :n, 'motd', 'prompt', 'grounded', :m, 1, 'UTC', :now, :now)"
            ).bindparams(sa.bindparam("now", type_=sa.DateTime())),
            {"id": str(uuid.uuid4()), "n": name, "m": model, "now": now},
        )


async def _models(engine: AsyncEngine) -> dict[str, str]:
    async with engine.begin() as conn:
        rows = (await conn.execute(sa.text("SELECT name, text_model_name FROM display_jobs"))).fetchall()
    return {row[0]: row[1] for row in rows}


async def test_retired_default_is_repointed_and_operator_choice_is_kept(seeded_engine: AsyncEngine) -> None:
    await _insert_job(seeded_engine, "on-old-default", _RETIRED)
    await _insert_job(seeded_engine, "operator-picked", "gemini-3-pro-preview")

    migration = load_migration("0029_retire_gemini_2_5_flash")
    async with seeded_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _run(sync_conn, migration))

    models = await _models(seeded_engine)
    assert models["on-old-default"] == _REPLACEMENT
    # A deliberate choice is left alone even though it is not the new default.
    assert models["operator-picked"] == "gemini-3-pro-preview"


async def test_rerun_is_idempotent(seeded_engine: AsyncEngine) -> None:
    await _insert_job(seeded_engine, "job", _RETIRED)
    migration = load_migration("0029_retire_gemini_2_5_flash")
    for _ in range(2):
        async with seeded_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _run(sync_conn, migration))
    assert (await _models(seeded_engine))["job"] == _REPLACEMENT


async def test_new_jobs_default_to_the_replacement() -> None:
    # The model default and the shared fallback must not drift apart, or a job
    # created without an explicit model would still land on the retired one.
    assert DisplayJob(name="x", content_prompt="y").text_model_name == _REPLACEMENT
    assert DEFAULT_TEXT_MODEL == _REPLACEMENT


def _run(sync_conn: sa.engine.Connection, migration: ModuleType) -> None:
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        migration.upgrade()


async def test_image_preset_on_the_retiring_default_is_repointed(seeded_engine: AsyncEngine) -> None:
    """0030 moves presets off gemini-2.5-flash-image but spares chosen models."""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with seeded_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE prompt_presets SET model_name = 'gemini-2.5-flash-image', updated_at = :now").bindparams(
                sa.bindparam("now", type_=sa.DateTime())
            ),
            {"now": now},
        )
        # One preset an operator pinned deliberately.
        await conn.execute(sa.text("UPDATE prompt_presets SET model_name = 'imagen-4' WHERE name = 'bookshelf_hero'"))

    migration = load_migration("0030_retire_gemini_2_5_flash_image")
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
