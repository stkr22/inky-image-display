"""Uvicorn entry point assembling the FastAPI + Flet UI application."""

from __future__ import annotations

import logging

import flet.fastapi as flet_fastapi
import httpx
import uvicorn
from fastapi import APIRouter, FastAPI
from inky_image_display_shared.logging import setup_logging
from minio import Minio

from inky_image_display_ui import app as flet_app
from inky_image_display_ui.api_client import ApiClient
from inky_image_display_ui.config import Settings
from inky_image_display_ui.s3_proxy import router as media_router
from inky_image_display_ui.upload_proxy import router as upload_router

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok"}


def build_app(settings: Settings) -> FastAPI:
    """Assemble the FastAPI application that hosts the Flet UI and support routes.

    Routes are registered before the Flet mount at ``/`` because FastAPI
    matches routes in registration order and mounts are matched last.
    """
    minio_client = Minio(
        settings.s3_endpoint,
        access_key=settings.s3_reader_access_key,
        secret_key=settings.s3_reader_secret_key,
        secure=settings.s3_secure,
        region=settings.s3_region or None,
    )
    http_client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=settings.api_timeout_seconds,
    )
    api_client = ApiClient(http_client)

    flet_app.configure(api_client=api_client)

    async def _on_startup() -> None:
        logger.info("Inky Image Display UI started on %s:%d", settings.host, settings.port)

    async def _on_shutdown() -> None:
        await http_client.aclose()
        logger.info("Inky Image Display UI stopped")

    # flet_fastapi.FastAPI owns the lifespan to coordinate its own Flet
    # app_manager startup/shutdown; we attach our httpx cleanup via on_shutdown.
    app = flet_fastapi.FastAPI(
        title="Inky Image Display UI",
        on_startup=[_on_startup],
        on_shutdown=[_on_shutdown],
    )
    app.state.settings = settings
    app.state.minio_client = minio_client
    app.state.api_client = api_client

    app.include_router(health_router)
    app.include_router(media_router)
    app.include_router(upload_router)
    app.mount("/", flet_fastapi.app(flet_app.main))
    return app


def main() -> None:
    """Run the UI server via uvicorn."""
    setup_logging()
    settings = Settings()  # ty: ignore[missing-argument]
    app = build_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        root_path=settings.root_path,
    )
