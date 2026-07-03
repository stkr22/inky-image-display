"""FastAPI application entry point."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from inky_image_display_shared.logging import setup_logging

from inky_image_display_api.config import Settings
from inky_image_display_api.database import create_engine, create_tables
from inky_image_display_api.mqtt import MQTTService
from inky_image_display_api.routes import (
    app_settings,
    device_profiles,
    devices,
    gemini_sync_jobs,
    genai_generate,
    grids,
    images,
    images_process,
    immich_browse,
    media,
    motd,
    prompt_blocks,
    prompt_presets,
    schedule,
    sync_jobs,
)
from inky_image_display_api.routes.health import router as health_router
from inky_image_display_api.services.generation_tasks import GenerationTaskRegistry
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
    app.state.generation_tasks = GenerationTaskRegistry()

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
app.include_router(images_process.router)
app.include_router(devices.router)
app.include_router(device_profiles.router)
app.include_router(grids.router)
app.include_router(schedule.router)
app.include_router(sync_jobs.router)
app.include_router(prompt_blocks.router)
app.include_router(prompt_presets.router)
app.include_router(gemini_sync_jobs.router)
app.include_router(genai_generate.router)
app.include_router(motd.router)
app.include_router(immich_browse.router)
app.include_router(app_settings.router)
app.include_router(media.router)


# Registered last so every explicit route above wins; serves the built React
# frontend (when API_WEB_DIST_PATH is set) with an SPA fallback to index.html
# for client-side routes like /images/<uuid>.
@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str, request: Request) -> Response:
    """Serve the static frontend bundle, falling back to index.html."""
    dist = request.app.state.settings.web_dist_path
    if not dist:
        raise HTTPException(status_code=404, detail="Not found")
    base = Path(dist).resolve()
    candidate = (base / full_path).resolve() if full_path else base
    if candidate.is_file() and candidate.is_relative_to(base):
        return FileResponse(candidate)
    index = base / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")


def main() -> None:
    """Run the API server via uvicorn."""
    setup_logging()
    uvicorn.run(
        "inky_image_display_api.main:app",
        host="0.0.0.0",
        port=8000,
    )
