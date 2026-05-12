"""Immich integration for fetching images from self-hosted Immich instances."""

from inky_image_display_sync.immich.api_client import ImmichDisplayAPIClient, SyncJobItem
from inky_image_display_sync.immich.client import ImmichClient
from inky_image_display_sync.immich.config import (
    APIClientConfig,
    DeviceRequirements,
    ImmichConnectionConfig,
    ImmichSyncConfig,
    S3WriterConfig,
)
from inky_image_display_sync.immich.sync_service import ImmichSyncService

__all__ = [
    "APIClientConfig",
    "DeviceRequirements",
    "ImmichClient",
    "ImmichConnectionConfig",
    "ImmichDisplayAPIClient",
    "ImmichSyncConfig",
    "ImmichSyncService",
    "S3WriterConfig",
    "SyncJobItem",
]
