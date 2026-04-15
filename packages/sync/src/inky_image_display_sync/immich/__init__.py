"""Immich integration for fetching images from self-hosted Immich instances."""

from inky_image_display_sync.immich.client import ImmichClient
from inky_image_display_sync.immich.config import (
    DeviceRequirements,
    ImmichConnectionConfig,
    ImmichSyncConfig,
    S3WriterConfig,
)
from inky_image_display_sync.immich.sync_service import ImmichSyncService

__all__ = [
    "DeviceRequirements",
    "ImmichClient",
    "ImmichConnectionConfig",
    "ImmichSyncConfig",
    "ImmichSyncService",
    "S3WriterConfig",
]
