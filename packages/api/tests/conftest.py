"""Shared test fixtures for the API package."""

import asyncio
import importlib.util
import os
import shutil
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.auth import AuthRuntime, SessionAuthMiddleware
from inky_image_display_api.config import Settings
from inky_image_display_api.database import _MIGRATIONS_DIR
from inky_image_display_api.main import register_routers
from inky_image_display_api.services.generation_tasks import GenerationTaskStore
from inky_image_display_shared.models import Device, DeviceProfile, Image
from inky_image_display_shared.time import utcnow
from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture(scope="session")
def schema_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An empty database with every model table, built once per session.

    ``create_all`` on a file database costs about half a second (one fsync
    per DDL statement); copying the finished file is near-free.
    """
    path = tmp_path_factory.mktemp("schema") / "template.db"
    engine = sa.create_engine(f"sqlite:///{path}", poolclass=NullPool)
    try:
        # Importing the models module registers every table on the shared
        # metadata, so create_all can't drift from the models the way a
        # hand-maintained list did.
        SQLModel.metadata.create_all(engine)
    finally:
        engine.dispose()
    return path


@pytest.fixture
async def async_engine(schema_template: Path, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A file-based SQLite async engine on a private copy of the schema.

    Uses ``NullPool`` so connections are opened and closed per-operation,
    avoiding event-loop entanglement when TestClient (anyio) tears down.
    """
    db_path = tmp_path / "test.db"
    shutil.copy(schema_template, db_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``API_*`` variables so the dev shell's config can't leak in.

    The devcontainer exports real S3/MQTT/database settings; a ``Settings``
    built in a test would silently pick them up, and the alembic CLI path
    would migrate whatever ``API_DATABASE_PATH`` points at.
    """
    for name in list(os.environ):
        if name.startswith("API_"):
            monkeypatch.delenv(name)


def make_settings(**overrides: Any) -> Settings:
    """Build a real ``Settings`` with every required field filled in.

    A real instance rather than a MagicMock: unset mock attributes are
    truthy, which once fired real notifications, exposed the debug routes
    and broke ``asyncio.Semaphore`` in unrelated tests.
    """
    values: dict[str, Any] = {
        "database_path": "/nonexistent/test.db",
        "s3_endpoint": "s3.test.local:9000",
        "s3_writer_access_key": "writer-key",
        "s3_writer_secret_key": "writer-secret",
        "s3_reader_access_key": "reader-key",
        "s3_reader_secret_key": "reader-secret",
        "mqtt_host": "broker.test",
        "device_mqtt_host": "broker.public.test",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    """Settings for the test app; tests may assign fields to vary them.

    Uses the split-endpoint layout (controllers reach S3 and MQTT over a
    public path) so registration tests can tell the two apart.
    """
    return make_settings(
        s3_bucket="test-images",
        device_s3_endpoint="s3.public.test",
        device_s3_secure=True,
        device_mqtt_port=443,
        device_mqtt_tls=True,
        device_mqtt_transport="websockets",
    )


def alembic_upgrade(db_path: Path, revision: str = "head") -> None:
    """Migrate the SQLite file at ``db_path`` to ``revision`` the way the app does."""
    _alembic(db_path, "upgrade", revision)


def alembic_downgrade(db_path: Path, revision: str) -> None:
    """Step the SQLite file at ``db_path`` back to ``revision``."""
    _alembic(db_path, "downgrade", revision)


def _alembic(db_path: Path, direction: str, revision: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    engine = sa.create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    try:
        with engine.begin() as conn:
            # Hand alembic the connection so env.py never falls back to a URL.
            cfg.attributes["connection"] = conn
            getattr(command, direction)(cfg, revision)
    finally:
        engine.dispose()


def load_migration(stem: str) -> ModuleType:
    """Import a migration module by file stem so its helpers can run in isolation."""
    path = _MIGRATIONS_DIR / "versions" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database migrated to head once per session.

    Running the full chain costs about a second; tests that need real
    seeded data copy this file instead of paying that per test.
    """
    path = tmp_path_factory.mktemp("migrated") / "template.db"
    alembic_upgrade(path)
    return path


@pytest.fixture
def migrated_db(migrated_template: Path, tmp_path: Path) -> Path:
    """A private copy of the migrated template, safe to mutate."""
    path = tmp_path / "migrated.db"
    shutil.copy(migrated_template, path)
    return path


@pytest.fixture
async def seeded_engine(migrated_db: Path) -> AsyncIterator[AsyncEngine]:
    """Engine on a fully migrated DB — exercises the real seed data."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{migrated_db}", poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


def no_such_key() -> S3Error:
    """The error MinIO raises for a missing object."""
    return S3Error(
        code="NoSuchKey", message="missing", resource="/x", request_id="r", host_id="h", response=MagicMock()
    )


@pytest.fixture
def mock_s3_service() -> MagicMock:
    """Create a mock S3 service."""
    s3 = MagicMock()
    s3.upload_image = MagicMock()
    s3.delete_object = MagicMock()
    # An empty bucket by default: derived-object caches must see a real
    # not-found (a bare MagicMock stat would read as "cached").
    s3.stat_object = MagicMock(side_effect=no_such_key())
    s3.list_keys = MagicMock(return_value=[])
    return s3


@pytest.fixture
def mock_mqtt() -> MagicMock:
    """Provide a stand-in for ``MQTTService`` in route-level tests.

    Routes only touch ``is_connected`` and ``send_command``; mock those.
    """
    mqtt = MagicMock()
    mqtt.is_connected = MagicMock(return_value=False)
    mqtt.send_command = AsyncMock()
    mqtt.publish_wake = AsyncMock()
    mqtt.worker_online = False
    return mqtt


@pytest.fixture
def auth_runtime() -> AuthRuntime:
    """Auth disabled (trusted-LAN mode), mirroring existing deployments.

    Auth-specific tests replace ``app.state.auth`` with enabled variants —
    the middleware reads it per request, so mutation after app creation
    works.
    """
    return AuthRuntime(
        enabled=False,
        session_secret="test-secret",
        cookie_secure=False,
        admin_session_ttl_seconds=3600,
        guest_session_ttl_seconds=1800,
        guest_invite_ttl_seconds=600,
        sync_token=None,
        device_token=None,
        public_base_url=None,
    )


@pytest.fixture
def test_app(
    async_engine: AsyncEngine,
    settings: Settings,
    mock_s3_service: MagicMock,
    mock_mqtt: MagicMock,
    auth_runtime: AuthRuntime,
) -> FastAPI:
    """Create a FastAPI test app with mocked state."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[misc]
        yield
        await async_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionAuthMiddleware)
    app.state.engine = async_engine
    app.state.settings = settings
    app.state.s3_service = mock_s3_service
    app.state.mqtt = mock_mqtt
    app.state.auth = auth_runtime
    app.state.process_gate = asyncio.Semaphore(settings.image_process_concurrency)
    app.state.thumb_gate = threading.BoundedSemaphore(settings.media_thumbnail_concurrency)
    app.state.generation_tasks = GenerationTaskStore(async_engine)

    register_routers(app)

    return app


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """Provide a synchronous test client."""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
async def seed_profile(async_engine: AsyncEngine) -> DeviceProfile:
    """Insert the default 13.3" Spectra 6 device profile."""
    profile = DeviceProfile(
        id=uuid4(),
        key="inky_impression_13_spectra6",
        name='Inky Impression 13.3" Spectra 6',
        width=1600,
        height=1200,
        physical_width_cm=27.1,
        physical_height_cm=20.3,
        model="inky_impression_13_spectra6",
        is_default=True,
    )
    async with AsyncSession(async_engine) as session:
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


@pytest.fixture
async def seed_device(async_engine: AsyncEngine, seed_profile: DeviceProfile) -> Device:
    """Insert a sample device into the test database."""
    device = Device(
        id=uuid4(),
        device_id="test-display",
        room="Living Room",
        device_profile_id=seed_profile.id,
        display_orientation="landscape",
        is_online=True,
        last_seen=utcnow(),
    )
    async with AsyncSession(async_engine) as session:
        session.add(device)
        await session.commit()
        await session.refresh(device)
    return device


@pytest.fixture
async def seed_image(async_engine: AsyncEngine) -> Image:
    """Insert a sample image into the test database."""
    image = Image(
        id=uuid4(),
        source_name="manual",
        storage_path="manual/test.jpg",
        title="Test Image",
        original_width=1600,
        original_height=1200,
        is_portrait=False,
    )
    async with AsyncSession(async_engine) as session:
        session.add(image)
        await session.commit()
        await session.refresh(image)
    return image


async def add_images(async_engine: AsyncEngine, count: int) -> list[Image]:
    """Insert ``count`` panel-sized images, oldest-shown first."""
    images = []
    base = utcnow() - timedelta(days=count)
    async with AsyncSession(async_engine) as session:
        for i in range(count):
            image = Image(
                source_name="manual",
                storage_path=f"manual/{uuid4()}.jpg",
                title=f"img-{i}",
                original_width=1600,
                original_height=1200,
                is_portrait=False,
                last_displayed_at=base + timedelta(hours=i),
            )
            session.add(image)
            images.append(image)
        await session.commit()
        for image in images:
            await session.refresh(image)
    return images
