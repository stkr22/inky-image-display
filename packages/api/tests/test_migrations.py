"""The migration chain must build a complete, model-matching schema from nothing.

The schema is hybrid (create_all bootstrap + incremental migrations), so the
realistic failures are a bootstrap list that misses a table a later
migration reflects, and models that drift from what the migrations build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from inky_image_display_api._migrations.bootstrap import target_metadata
from inky_image_display_api.database import _MIGRATIONS_DIR, create_tables
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _table_names(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_bare_alembic_upgrade_on_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``alembic upgrade head`` via URL (the CLI path) used to crash on image_groups."""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setenv("API_DATABASE_PATH", str(db_path))
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///placeholder-overridden-by-env.db")

    command.upgrade(cfg, "head")

    assert set(target_metadata.tables) <= _table_names(db_path)


async def test_app_upgrade_uses_its_own_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambient API_DATABASE_PATH must not redirect the app's migration elsewhere."""
    app_db = tmp_path / "app.db"
    decoy = tmp_path / "decoy.db"
    monkeypatch.setenv("API_DATABASE_PATH", str(decoy))
    engine = create_async_engine(f"sqlite+aiosqlite:///{app_db}", poolclass=NullPool)
    try:
        await create_tables(engine)
        # Idempotent: a second startup against a migrated DB is a no-op.
        await create_tables(engine)
    finally:
        await engine.dispose()

    assert set(target_metadata.tables) <= _table_names(app_db)
    assert not decoy.exists()


def test_models_match_migrated_schema(migrated_template: Path) -> None:
    """Autogenerate against a migrated DB must find nothing to change.

    Bootstrapped tables come straight from the models, so this mostly guards
    the migration-owned tables (device_profiles, app_settings,
    calibre_sync_jobs, image_books) against model edits without a migration.
    Read-only, so the shared session template is safe to inspect directly.
    """
    sync_engine = sa.create_engine(f"sqlite:///{migrated_template}")
    try:
        with sync_engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(context, target_metadata)
    finally:
        sync_engine.dispose()
    assert diff == []
