"""Shared test fixtures for the API package."""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.routes import devices, images, sync_jobs
from inky_image_display_api.websocket import ConnectionManager
from inky_image_display_api.websocket import router as ws_router
from inky_image_display_shared.models import Device, Image
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    """Create an in-memory SQLite async engine for testing.

    Uses ``StaticPool`` so every connection sees the same in-memory
    database. Only creates the tables owned by the API.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for table in [Image.__table__, Device.__table__]:  # ty: ignore[unresolved-attribute]
            await conn.run_sync(table.create, checkfirst=True)
    yield engine
    await engine.dispose()


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
    return settings


@pytest.fixture
def mock_s3_service() -> MagicMock:
    """Create a mock S3 service."""
    s3 = MagicMock()
    s3.upload_image = MagicMock()
    s3.delete_object = MagicMock()
    return s3


@pytest.fixture
def connection_manager() -> ConnectionManager:
    """Create a fresh ConnectionManager."""
    return ConnectionManager()


@pytest.fixture
def test_app(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    connection_manager: ConnectionManager,
) -> FastAPI:
    """Create a FastAPI test app with mocked state."""
    app = FastAPI()
    app.state.engine = async_engine
    app.state.settings = mock_settings
    app.state.s3_service = mock_s3_service
    app.state.connection_manager = connection_manager

    app.include_router(ws_router)
    app.include_router(images.router)
    app.include_router(devices.router)
    app.include_router(sync_jobs.router)

    return app


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """Provide a synchronous test client."""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
async def seed_device(async_engine: AsyncEngine) -> Device:
    """Insert a sample device into the test database."""
    device = Device(
        id=uuid4(),
        device_id="test-display",
        room="Living Room",
        display_width=1600,
        display_height=1200,
        display_orientation="landscape",
        is_online=True,
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
