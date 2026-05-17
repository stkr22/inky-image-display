"""FastAPI application entry point."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from inky_image_display_shared.logging import setup_logging

from inky_image_display_api.config import Settings
from inky_image_display_api.database import create_engine, create_tables
from inky_image_display_api.mqtt import MQTTService
from inky_image_display_api.routes import (
    device_profiles,
    devices,
    gemini_sync_jobs,
    genai_generate,
    grids,
    images,
    prompt_blocks,
    prompt_presets,
    schedule,
    sync_jobs,
)
from inky_image_display_api.routes.health import router as health_router
from inky_image_display_api.services.rotation import rotation_loop
from inky_image_display_api.services.s3_service import S3Service

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

    # MQTT transport — replaces the previous WebSocket connection manager.
    mqtt = MQTTService(settings, engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.s3_service = s3_service
    app.state.mqtt = mqtt

    rotation_task = asyncio.create_task(rotation_loop(app))
    mqtt_task = asyncio.create_task(mqtt.run())

    logger.info("Inky Image Display API started")
    try:
        yield
    finally:
        for task in (rotation_task, mqtt_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await engine.dispose()
        logger.info("Inky Image Display API stopped")


app = FastAPI(title="Inky Image Display API", lifespan=lifespan)
app.include_router(health_router)
app.include_router(images.router)
app.include_router(devices.router)
app.include_router(device_profiles.router)
app.include_router(grids.router)
app.include_router(schedule.router)
app.include_router(sync_jobs.router)
app.include_router(prompt_blocks.router)
app.include_router(prompt_presets.router)
app.include_router(gemini_sync_jobs.router)
app.include_router(genai_generate.router)


def main() -> None:
    """Run the API server via uvicorn."""
    setup_logging()
    uvicorn.run(
        "inky_image_display_api.main:app",
        host="0.0.0.0",
        port=8000,
    )
