"""Regression coverage for the AI prompt-library seed and its UUID format.

These tests guard against the SQLite UUID format mismatch that originally hid
the seeded ``e_ink_humanoid`` preset from any ID-keyed lookup:

- migration 0004 used to insert via raw ``sa.text`` with ``str(uuid.uuid4())``
  (36-char with dashes), while ``sa.Uuid`` on SQLite stores ORM-bound UUIDs as
  32-char hex. Listing presets worked (no ID filter) but
  ``where(col(id) == preset_id)`` always missed.

The test below runs the real migrations on a fresh temp database, then drives
every code path the generate flow touches: the API's list+get endpoints, the
generation service's two ``resolve_preset`` branches, and the block fan-out.
A second test simulates a pre-fix prod database (rows already seeded with
dashes-form IDs) and asserts migration 0006 normalises them.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import inky_image_display_api
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.database import create_tables
from inky_image_display_api.routes.prompt_presets import router as presets_router
from inky_image_display_api.services.generation_service import resolve_preset
from inky_image_display_shared.models import PromptPreset
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType


@pytest.fixture
async def seeded_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    """Fresh SQLite DB with all migrations applied — exercises real seeding.

    The alembic ``env.py`` honours ``API_DATABASE_PATH`` and overrides the cfg
    URL with it. In dev environments where that var points at the shared
    workspace DB, tests would unwittingly migrate it. Point it at the temp DB
    for the duration of the fixture.
    """
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


class TestSeededPresetIsReachable:
    """The default preset must be findable through every lookup path."""

    async def test_default_preset_seeded(self, seeded_engine: AsyncEngine) -> None:
        """is_default branch must return the seeded preset row."""
        async with AsyncSession(seeded_engine) as session:
            result = await session.exec(select(PromptPreset).where(PromptPreset.is_default == True))  # noqa: E712
            preset = result.first()
        assert preset is not None
        assert preset.name == "e_ink_humanoid"

    async def testresolve_preset_without_id(self, seeded_engine: AsyncEngine) -> None:
        """``resolve_preset(None)`` (the dropdown-empty path) returns preset+blocks."""
        async with AsyncSession(seeded_engine) as session:
            preset, blocks = await resolve_preset(session, None)
        assert preset.name == "e_ink_humanoid"
        # Every FK on the preset must resolve to a block — this is what
        # exposed the bug end-to-end (in_-clause silently returning empty).
        assert len(blocks) == 5

    async def testresolve_preset_by_id(self, seeded_engine: AsyncEngine) -> None:
        """``resolve_preset(preset_id)`` (the UI-default path) must succeed.

        This is the exact path that failed in prod with "No prompt preset
        available" — the UUID stored in dashes form never matched the
        ORM-bound hex form.
        """
        async with AsyncSession(seeded_engine) as session:
            result = await session.exec(select(PromptPreset).where(PromptPreset.is_default == True))  # noqa: E712
            seeded = result.first()
        assert seeded is not None

        async with AsyncSession(seeded_engine) as session:
            preset, blocks = await resolve_preset(session, seeded.id)
        assert preset.id == seeded.id
        assert len(blocks) == 5

    async def test_list_then_get_roundtrip(self, seeded_engine: AsyncEngine) -> None:
        """The UI flow: list presets, then submit one by id — both must work.

        Mirrors what the UI does: ``GET /api/genai/presets`` populates the
        dropdown; the chosen id is then sent back. Both endpoints must agree
        on the row's identity.
        """
        app = FastAPI()
        app.state.engine = seeded_engine
        app.include_router(presets_router)
        with TestClient(app) as client:
            listed = client.get("/api/genai/presets").json()
            assert any(p["name"] == "e_ink_humanoid" for p in listed)
            preset_id = next(p["id"] for p in listed if p["name"] == "e_ink_humanoid")
            single = client.get(f"/api/genai/presets/{preset_id}")
            assert single.status_code == 200, single.text
            assert single.json()["id"] == preset_id


class TestDefaultBlocksRepainted:
    """Migration 0013 must repaint the seeded defaults but spare operator edits."""

    async def test_repaint_applied_on_fresh_db(self, seeded_engine: AsyncEngine) -> None:
        """A fresh DB (all migrations applied) carries the repainted text, not the 0004 seed."""
        async with seeded_engine.begin() as conn:
            rows = (await conn.execute(sa.text("SELECT name, text FROM prompt_blocks WHERE is_default = 1"))).fetchall()
        text_by_name = {row[0]: row[1] for row in rows}

        # Palette is now a blacklist that leans on dithering, not a six-colour whitelist.
        assert "dither" in text_by_name["spectra_6"].lower()
        assert "Use only six colors" not in text_by_name["spectra_6"]
        # Style invites painterly depth instead of flat blocks.
        assert "painterly" in text_by_name["poster_screenprint"].lower()
        assert "flat color blocks" not in text_by_name["poster_screenprint"]

    async def test_operator_edited_block_is_preserved(self, seeded_engine: AsyncEngine) -> None:
        """A block whose text was changed in the UI must survive a 0013 re-run untouched."""
        mig0013 = _load_migration("0013_repaint_default_prompt_blocks")
        custom = "MY HAND-TUNED PALETTE — keep this."

        async with seeded_engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE prompt_blocks SET text = :t WHERE name = 'spectra_6'"),
                {"t": custom},
            )
            await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, mig0013))

        async with seeded_engine.begin() as conn:
            text = (await conn.execute(sa.text("SELECT text FROM prompt_blocks WHERE name = 'spectra_6'"))).scalar_one()
        assert text == custom


class TestDefaultBlocksTuned:
    """Migration 0015 must retune the defaults but spare operator edits."""

    async def test_tuning_applied_on_fresh_db(self, seeded_engine: AsyncEngine) -> None:
        """A fresh DB carries the tuned text: no named artist, hard no-text rule."""
        async with seeded_engine.begin() as conn:
            rows = (await conn.execute(sa.text("SELECT name, text FROM prompt_blocks"))).fetchall()
        text_by_name = {row[0]: row[1] for row in rows}

        # Named artists leak into content (Van Gogh painted himself into MOTD
        # illustrations); the style now names only the painterly qualities.
        assert "Van Gogh" not in text_by_name["poster_screenprint"]
        assert "painterly" in text_by_name["poster_screenprint"].lower()
        # Generated captions dither badly and misspell — text is forbidden.
        assert "no text of any kind" in text_by_name["eink_bold_shapes"]
        # The scene block is now a generic hero-subject composition.
        assert "emblematic" in text_by_name["scene_full_frame"]

    async def test_operator_edited_block_is_preserved(self, seeded_engine: AsyncEngine) -> None:
        """A block edited in the UI must survive a 0015 re-run untouched."""
        mig0015 = _load_migration("0015_add_motd")
        custom = "MY HAND-TUNED STYLE — keep this."

        async with seeded_engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE prompt_blocks SET text = :t WHERE name = 'poster_screenprint'"),
                {"t": custom},
            )
            await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, mig0015))

        async with seeded_engine.begin() as conn:
            text = (
                await conn.execute(sa.text("SELECT text FROM prompt_blocks WHERE name = 'poster_screenprint'"))
            ).scalar_one()
        assert text == custom


class TestScenePresetSeeded:
    """Migration 0015 must seed the scene preset for MOTD image generation."""

    async def test_scene_preset_seeded_with_scene_composition(self, seeded_engine: AsyncEngine) -> None:
        async with seeded_engine.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT p.is_default, b.name FROM prompt_presets p "
                        "JOIN prompt_blocks b ON b.id = p.composition_block_id WHERE p.name = 'e_ink_scene'"
                    )
                )
            ).fetchone()
        assert row is not None, "e_ink_scene preset missing"
        assert not row[0], "scene preset must not displace the library default"
        assert row[1] == "scene_full_frame"

    async def test_seed_is_idempotent(self, seeded_engine: AsyncEngine) -> None:
        mig0015 = _load_migration("0015_add_motd")
        async with seeded_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, mig0015))
        async with seeded_engine.begin() as conn:
            count = (
                await conn.execute(sa.text("SELECT COUNT(*) FROM prompt_presets WHERE name = 'e_ink_scene'"))
            ).scalar_one()
        assert count == 1


class TestUuidFormatBackfill:
    """Migration 0006 must repair already-deployed dashes-form rows."""

    async def test_backfill_normalises_existing_dashed_ids(self, seeded_engine: AsyncEngine) -> None:
        """Inject dashes-form rows like pre-fix prod, re-run 0006, verify lookups."""
        mig0006 = _load_migration("0006_normalize_seeded_uuid_format")

        # Wipe the (correctly-formatted) seed so we can plant pre-fix data.
        async with seeded_engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM prompt_presets"))
            await conn.execute(sa.text("DELETE FROM prompt_blocks"))

            block_ids = {kind: str(uuid.uuid4()) for kind in ("s", "p", "l", "c", "b")}
            now = datetime.now().isoformat(sep=" ")
            for kind_short, full_kind in (
                ("s", "style"),
                ("p", "palette"),
                ("l", "legibility"),
                ("c", "composition"),
                ("b", "background"),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO prompt_blocks (id, kind, name, text, is_default, "
                        "created_at, updated_at) VALUES (:id, :k, :n, 't', 1, :now, :now)"
                    ),
                    {"id": block_ids[kind_short], "k": full_kind, "n": full_kind, "now": now},
                )
            preset_id = str(uuid.uuid4())
            await conn.execute(
                sa.text(
                    "INSERT INTO prompt_presets (id, name, style_block_id, "
                    "palette_block_id, legibility_block_id, composition_block_id, "
                    "background_block_id, is_default, model_name, created_at, updated_at) "
                    "VALUES (:id, 'legacy', :s, :p, :l, :c, :b, 1, 'm', :now, :now)"
                ),
                {
                    "id": preset_id,
                    "s": block_ids["s"],
                    "p": block_ids["p"],
                    "l": block_ids["l"],
                    "c": block_ids["c"],
                    "b": block_ids["b"],
                    "now": now,
                },
            )

        # Pre-condition: ORM ID lookup fails on dashes-form data (the bug).
        async with AsyncSession(seeded_engine) as session:
            r = await session.exec(select(PromptPreset).where(col(PromptPreset.id) == uuid.UUID(preset_id)))
            assert r.first() is None, "expected dashed-form rows to be unreachable by ORM"

        # Run migration 0006's upgrade against the live connection.
        async with seeded_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, mig0006))

        # Post-condition: every ID-keyed lookup now succeeds.
        async with AsyncSession(seeded_engine) as session:
            preset, blocks = await resolve_preset(session, uuid.UUID(preset_id))
        assert preset.name == "legacy"
        assert len(blocks) == 5


def _load_migration(stem: str) -> ModuleType:
    """Import a migration module by file stem so its upgrade() can run in isolation."""
    api_root = Path(inky_image_display_api.__file__).parent
    spec = importlib.util.spec_from_file_location(stem, api_root / "_migrations" / "versions" / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(sync_conn: sa.engine.Connection, mig_module: ModuleType) -> None:
    """Invoke a migration's ``upgrade()`` against an existing connection.

    Alembic's ``op`` proxy needs a ``MigrationContext`` bound to a connection;
    setting one up by hand lets us run a single migration in isolation from a
    test without spinning up the whole alembic config.
    """
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        mig_module.upgrade()
