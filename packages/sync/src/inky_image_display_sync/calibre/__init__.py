"""Calibre-Web integration for building displays from a book library."""

from inky_image_display_sync.calibre.api_client import CalibreDisplayAPIClient, CalibreSyncJobItem
from inky_image_display_sync.calibre.client import (
    BookFilter,
    CalibreBook,
    CalibreClient,
    CalibreError,
    parse_catalog,
    select_books,
)
from inky_image_display_sync.calibre.config import CalibreConnectionConfig
from inky_image_display_sync.calibre.sync_service import CalibreSyncResult, CalibreSyncService

__all__ = [
    "BookFilter",
    "CalibreBook",
    "CalibreClient",
    "CalibreConnectionConfig",
    "CalibreDisplayAPIClient",
    "CalibreError",
    "CalibreSyncJobItem",
    "CalibreSyncResult",
    "CalibreSyncService",
    "parse_catalog",
    "select_books",
]
