"""Uvicorn entry point assembling the FastAPI + NiceGUI UI application."""

from __future__ import annotations

import logging

import httpx
import uvicorn
from fastapi import APIRouter, FastAPI
from inky_image_display_shared.logging import setup_logging
from minio import Minio
from nicegui import app as nicegui_app
from nicegui import ui

from inky_image_display_ui import app as ui_app
from inky_image_display_ui.api_client import ApiClient
from inky_image_display_ui.config import Settings
from inky_image_display_ui.s3_proxy import router as media_router

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok"}


def build_app(settings: Settings) -> FastAPI:
    """Assemble the FastAPI application that hosts the NiceGUI UI and support routes.

    The /health and /media routers are registered before NiceGUI mounts itself,
    so FastAPI matches them ahead of NiceGUI's catch-all SPA routes.
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

    ui_app.configure(api_client=api_client)

    app = FastAPI(title="Inky Image Display UI")
    app.state.settings = settings
    app.state.minio_client = minio_client
    app.state.api_client = api_client
    app.state.http_client = http_client

    app.include_router(health_router)
    app.include_router(media_router)

    ui_app.register_pages()
    ui.run_with(
        app,
        title="Inky Image Display",
        storage_secret=settings.storage_secret,
    )

    async def _close_http_client() -> None:
        await http_client.aclose()
        logger.info("Inky Image Display UI stopped")

    nicegui_app.on_shutdown(_close_http_client)
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


if __name__ in {"__main__", "__mp_main__"}:
    main()
