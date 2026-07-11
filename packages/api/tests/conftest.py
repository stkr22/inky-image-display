"""Shared test fixtures for the API package."""

import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.auth import AuthRuntime, SessionAuthMiddleware
from inky_image_display_api.routes import (
    app_settings,
    auth,
    device_profiles,
    devices,
    gemini_sync_jobs,
    grids,
    images,
    images_process,
    motd,
    prompt_blocks,
    schedule,
    sync_jobs,
)
from inky_image_display_api.routes.health import router as health_router
from inky_image_display_shared.models import (
    AppSetting,
    Device,
    DeviceProfile,
    GeminiSyncJob,
    Grid,
    GridDevice,
    Image,
    MotdConfig,
    MotdDeviceAssignment,
    MotdMessage,
    MotdScreen,
    PromptBlock,
    PromptPreset,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    """Create a file-based SQLite async engine for testing.

    Uses ``NullPool`` so connections are opened and closed per-operation,
    avoiding event-loop entanglement when TestClient (anyio) tears down.
    """
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        for table in [
            Image.__table__,  # ty: ignore[unresolved-attribute]
            DeviceProfile.__table__,  # ty: ignore[unresolved-attribute]
            Grid.__table__,  # ty: ignore[unresolved-attribute]
            PromptBlock.__table__,  # ty: ignore[unresolved-attribute]
            PromptPreset.__table__,  # ty: ignore[unresolved-attribute]
            MotdConfig.__table__,  # ty: ignore[unresolved-attribute]
            Device.__table__,  # ty: ignore[unresolved-attribute]
            GridDevice.__table__,  # ty: ignore[unresolved-attribute]
            AppSetting.__table__,  # ty: ignore[unresolved-attribute]
            GeminiSyncJob.__table__,  # ty: ignore[unresolved-attribute]
            MotdDeviceAssignment.__table__,  # ty: ignore[unresolved-attribute]
            MotdMessage.__table__,  # ty: ignore[unresolved-attribute]
            MotdScreen.__table__,  # ty: ignore[unresolved-attribute]
        ]:
            await conn.run_sync(table.create, checkfirst=True)
    yield engine
    db_path.unlink(missing_ok=True)


@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock settings with sensible defaults."""
    settings = MagicMock()
    settings.s3_endpoint = "s3.test.local:9000"
    settings.s3_bucket = "test-images"
    settings.s3_secure = False
    settings.s3_region = None
    settings.s3_reader_access_key = "reader-key"
    settings.s3_reader_secret_key = "reader-secret"
    settings.default_display_duration = 3600
    settings.refresh_error_backoff_seconds = 900
    settings.mqtt_host = "broker.test"
    settings.mqtt_port = 1883
    settings.mqtt_username = None
    settings.mqtt_password = None
    settings.mqtt_tls = False
    settings.mqtt_transport = "tcp"
    settings.mqtt_websocket_path = "/mqtt"
    settings.mqtt_keep_alive = 30
    settings.device_mqtt_host = "broker.public.test"
    settings.device_mqtt_port = 443
    settings.device_mqtt_username = None
    settings.device_mqtt_password = None
    settings.device_mqtt_tls = True
    settings.device_mqtt_transport = "websockets"
    settings.device_mqtt_websocket_path = "/mqtt"
    settings.device_mqtt_keep_alive = 30
    return settings


@pytest.fixture
def mock_s3_service() -> MagicMock:
    """Create a mock S3 service."""
    s3 = MagicMock()
    s3.upload_image = MagicMock()
    s3.delete_object = MagicMock()
    return s3


@pytest.fixture
def mock_mqtt() -> MagicMock:
    """Provide a stand-in for ``MQTTService`` in route-level tests.

    Routes only touch ``is_connected``, ``send_command`` and
    ``connected_device_ids``; mock those.
    """
    mqtt = MagicMock()
    mqtt.online_devices = set()
    mqtt.is_connected = MagicMock(return_value=False)
    mqtt.connected_device_ids = MagicMock(return_value=[])
    mqtt.send_command = AsyncMock()
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
    mock_settings: MagicMock,
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
    app.state.settings = mock_settings
    app.state.s3_service = mock_s3_service
    app.state.mqtt = mock_mqtt
    app.state.auth = auth_runtime

    app.include_router(health_router)
    app.include_router(auth.router)
    app.include_router(images.router)
    app.include_router(images_process.router)
    app.include_router(devices.router)
    app.include_router(device_profiles.router)
    app.include_router(grids.router)
    app.include_router(schedule.router)
    app.include_router(sync_jobs.router)
    app.include_router(app_settings.router)
    app.include_router(prompt_blocks.router)
    app.include_router(gemini_sync_jobs.router)
    app.include_router(motd.router)

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
        last_seen=datetime.now(),
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
