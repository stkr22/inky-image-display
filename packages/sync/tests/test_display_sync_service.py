"""Tests for the display-job worker's failure handling.

Gemini, S3 and the Display API are mocked at the client boundary. What is
pinned here is that a claimed job always gets a run report and that a run
which dies half-way never leaves a partly filled image group in the queue.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from inky_image_display_shared.ai.gemini_text import MotdStory
from inky_image_display_shared.schemas.responses import DisplayJobClaim, DisplayJobClaimSlot, ImageGroupResponse
from inky_image_display_shared.time import utcnow
from inky_image_display_sync.display.api_client import DisplayJobAPIClient
from inky_image_display_sync.display.sync_service import DisplayJobSyncService
from inky_image_display_sync.gemini.config import GeminiConnectionConfig
from inky_image_display_sync.storage import S3WriterConfig

_SERVICE = "inky_image_display_sync.display.sync_service"

_STORY = MotdStory(
    headline="Headline",
    what="What",
    why="Why",
    when_text="When",
    takeaway="Takeaway",
    image_subject="A subject",
)


def _job(name: str = "motd") -> DisplayJobClaim:
    return DisplayJobClaim(
        id=uuid4(),
        name=name,
        target_grid_id=uuid4(),
        content_prompt="news",
        source_mode="grounded",
        image_preset_id=None,
        text_model_name="gemini-text",
        slots=[
            DisplayJobClaimSlot(
                row=0,
                col=col,
                parts=["headline", "what"],
                device_id=f"d{col}",
                width=800,
                height=480,
                is_portrait=False,
            )
            for col in range(2)
        ],
    )


def _service(jobs: list[DisplayJobClaim]) -> tuple[DisplayJobSyncService, AsyncMock, AsyncMock]:
    api_client = AsyncMock(spec=DisplayJobAPIClient)
    api_client.claim_due_display_jobs.return_value = jobs
    api_client.create_image_group.return_value = ImageGroupResponse(
        id=uuid4(),
        name="Headline",
        target_grid_id=jobs[0].target_grid_id,
        display_job_id=jobs[0].id,
        description=None,
        source_url=None,
        queue_position=0,
        last_displayed_at=None,
        created_at=utcnow(),
    )
    api_client.render_part.return_value = b"screen"
    service = DisplayJobSyncService(
        api_client=api_client,
        logger=MagicMock(),
        gemini_config=GeminiConnectionConfig(api_key="k"),
        s3_config=S3WriterConfig(endpoint="localhost:9000", access_key="k", secret_key="s"),
    )
    storage = AsyncMock()
    service.storage = storage
    return service, api_client, storage


async def test_successful_run_fills_the_group_and_keeps_it() -> None:
    service, api_client, _ = _service([_job()])

    with patch(f"{_SERVICE}.generate_motd_story", AsyncMock(return_value=(_STORY, None))):
        results = await service.sync_jobs()

    assert results[0].screens == 4
    api_client.delete_image_group.assert_not_awaited()
    assert api_client.report_sync_run.await_args.args[0].status == "success"


async def test_upload_failure_mid_run_deletes_the_half_filled_group() -> None:
    service, api_client, storage = _service([_job()])
    storage.upload_from_bytes.side_effect = [None, RuntimeError("s3 down")]

    with patch(f"{_SERVICE}.generate_motd_story", AsyncMock(return_value=(_STORY, None))):
        results = await service.sync_jobs()

    group_id = api_client.create_image_group.return_value.id
    api_client.delete_image_group.assert_awaited_once_with(group_id)
    assert "s3 down" in results[0].errors[0]
    report = api_client.report_sync_run.await_args.args[0]
    assert (report.status, report.images_added) == ("error", 0)


async def test_registration_failure_deletes_the_group_and_next_job_still_runs() -> None:
    service, api_client, _ = _service([_job("first"), _job("second")])
    api_client.register_image.side_effect = [RuntimeError("api 500")] + [MagicMock()] * 4

    with patch(f"{_SERVICE}.generate_motd_story", AsyncMock(return_value=(_STORY, None))):
        results = await service.sync_jobs()

    assert [(r.job_name, r.screens) for r in results] == [("first", 0), ("second", 4)]
    api_client.delete_image_group.assert_awaited_once()
    reports = [c.args[0] for c in api_client.report_sync_run.await_args_list]
    assert [(r.job_name, r.status) for r in reports] == [("first", "error"), ("second", "success")]


async def test_group_creation_failure_is_still_reported() -> None:
    service, api_client, _ = _service([_job()])
    api_client.create_image_group.side_effect = RuntimeError("grid gone")

    with patch(f"{_SERVICE}.generate_motd_story", AsyncMock(return_value=(_STORY, None))):
        await service.sync_jobs()

    report = api_client.report_sync_run.await_args.args[0]
    assert report.status == "error"
    assert "grid gone" in report.error


async def test_failed_group_cleanup_does_not_mask_the_original_error() -> None:
    service, api_client, storage = _service([_job()])
    storage.upload_from_bytes.side_effect = RuntimeError("s3 down")
    api_client.delete_image_group.side_effect = RuntimeError("delete failed too")

    with patch(f"{_SERVICE}.generate_motd_story", AsyncMock(return_value=(_STORY, None))):
        results = await service.sync_jobs()

    assert "s3 down" in results[0].errors[0]
