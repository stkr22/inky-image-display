"""FastAPI application entry point."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from inky_image_display_api.config import Settings
from inky_image_display_api.database import create_engine, create_tables
from inky_image_display_api.routes import devices, images, sync_jobs
from inky_image_display_api.routes.health import router as health_router
from inky_image_display_api.services.rotation import rotation_loop
from inky_image_display_api.services.s3_service import S3Service
from inky_image_display_api.websocket import ConnectionManager
from inky_image_display_api.websocket import router as ws_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    settings = Settings()  # ty: ignore[missing-argument]

    # Database
    engine = create_engine(settings)
    await create_tables(engine)

    # S3
    s3_service = S3Service(settings)

    # Connection manager
    connection_manager = ConnectionManager()

    # Store on app.state for access in routes / websocket
    app.state.settings = settings
    app.state.engine = engine
    app.state.s3_service = s3_service
    app.state.connection_manager = connection_manager

    # Start background rotation task
    rotation_task = asyncio.create_task(rotation_loop(app))

    logger.info("Inky Image Display API started")
    try:
        yield
    finally:
        rotation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await rotation_task
        await engine.dispose()
        logger.info("Inky Image Display API stopped")


app = FastAPI(title="Inky Image Display API", lifespan=lifespan)
app.include_router(health_router)
app.include_router(ws_router)
app.include_router(images.router)
app.include_router(devices.router)
app.include_router(sync_jobs.router)


def main() -> None:
    """Run the API server via uvicorn."""
    uvicorn.run("inky_image_display_api.main:app", host="0.0.0.0", port=8000)
