"""Tests for the one-shot CLI runners."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_shared.schemas.responses import CalibreSyncJobResponse
from inky_image_display_shared.time import utcnow
from inky_image_display_sync.main import run_calibre_sync


def _bookcase_job() -> CalibreSyncJobResponse:
    now = utcnow()
    return CalibreSyncJobResponse(
        id=uuid4(),
        name="case",
        is_active=True,
        mode="bookcase",
        target_device_profile_id=uuid4(),
        prompt_preset_id=uuid4(),
        tags=[],
        languages=[],
        authors=[],
        books_per_shelf=5,
        shelf_rows=3,
        avoid_repeats=True,
        images_per_run=2,
        retention_days=None,
        verify_spines=True,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )


async def test_calibre_dry_run_counts_every_bookcase_shelf(caplog: pytest.LogCaptureFixture):
    api_client = AsyncMock()
    api_client.get_due_calibre_jobs.return_value = [_bookcase_job()]

    with (
        patch("inky_image_display_sync.main.APIClientConfig", MagicMock()),
        patch("inky_image_display_sync.main.CalibreDisplayAPIClient", return_value=api_client),
        caplog.at_level(logging.INFO, logger="inky_image_display_sync"),
    ):
        await run_calibre_sync(dry_run=True)

    # 5 books per shelf x 3 shelves, not just one shelf's worth.
    assert any("2 image(s) x 15 book(s)" in r.getMessage() for r in caplog.records)
    api_client.claim_due_calibre_jobs.assert_not_awaited()
