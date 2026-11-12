"""Tests for the Gemini batch sync service.

Gemini and the Display API are mocked at the client boundary; the tests pin
the orchestration that matters in production: the subjects x images_per_subject
fan-out, one failure not aborting the rest of the batch, orientation-driven
dimension handling, retention, and the payload registered with the API.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_shared.schemas.responses import (
    DeviceProfileResponse,
    GeminiSyncJobResponse,
    PromptBlockResponse,
    PromptPresetResponse,
)
from inky_image_display_shared.time import utcnow
from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.gemini.sync_service import GeminiSyncService, build_prompt
from inky_image_display_sync.storage import S3WriterConfig

_BLOCK_KINDS = ("style", "palette", "legibility", "composition", "background")
_NOW = utcnow()


def _make_blocks() -> list[PromptBlockResponse]:
    return [
        PromptBlockResponse(
            id=uuid4(),
            kind=kind,
            name=f"{kind}-default",
            text=f"{kind} text",
            is_default=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
        for kind in _BLOCK_KINDS
    ]


def _make_preset(blocks: list[PromptBlockResponse]) -> PromptPresetResponse:
    ids = {b.kind: b.id for b in blocks}
    return PromptPresetResponse(
        id=uuid4(),
        name="default",
        style_block_id=ids["style"],
        palette_block_id=ids["palette"],
        legibility_block_id=ids["legibility"],
        composition_block_id=ids["composition"],
        background_block_id=ids["background"],
        model_name="gemini-test-model",
        is_default=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_job(  # noqa: PLR0913, PLR0917 — test factory mirrors job fields
    name: str = "test-job",
    orientation: str = "landscape",
    subjects: list[str] | None = None,
    images_per_subject: int = 1,
    retention_days: int | None = None,
    prompt_preset_id=None,
) -> GeminiSyncJobResponse:
    return GeminiSyncJobResponse(
        id=uuid4(),
        name=name,
        is_active=True,
        target_device_profile_id=uuid4(),
        prompt_preset_id=prompt_preset_id or uuid4(),
        orientation=orientation,
        subjects=subjects if subjects is not None else ["a fox"],
        images_per_subject=images_per_subject,
        retention_days=retention_days,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_profile() -> DeviceProfileResponse:
    return DeviceProfileResponse(
        id=uuid4(),
        key="inky_impression_13_spectra6",
        name="Test profile",
        width=1600,
        height=1200,
        physical_width_cm=27.0,
        physical_height_cm=20.0,
        model="test-model",
        is_default=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service(api_client: AsyncMock) -> GeminiSyncService:
    service = GeminiSyncService(
        api_client=api_client,
        logger=MagicMock(),
        gemini_config=GeminiConnectionConfig(api_key="test-key"),
        sync_config=GeminiSyncConfig(storage_prefix="gemini"),
        s3_config=S3WriterConfig(
            endpoint="localhost:9000",
            bucket="test-bucket",
            secure=False,
            access_key="k",
            secret_key="s",
        ),
    )
    service.storage = AsyncMock()
    return service


def _api_client(blocks: list[PromptBlockResponse], preset: PromptPresetResponse) -> AsyncMock:
    api_client = AsyncMock(spec=GeminiDisplayAPIClient)
    api_client.list_prompt_blocks.return_value = blocks
    api_client.get_prompt_preset.return_value = preset
    api_client.get_device_profile.return_value = _make_profile()
    api_client.process_image.return_value = b"processed-jpeg"
    return api_client


async def test_no_active_jobs_returns_empty() -> None:
    api_client = AsyncMock(spec=GeminiDisplayAPIClient)
    api_client.get_active_gemini_jobs.return_value = []
    service = _make_service(api_client)

    assert await service.sync_jobs(all_active=True) == []
    service.storage.ensure_bucket_exists.assert_called_once()  # ty: ignore[missing-attribute]


async def test_fan_out_generates_subjects_times_count_and_registers() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    job = _make_job(subjects=["a fox", "a heron"], images_per_subject=2)
    api_client.get_active_gemini_jobs.return_value = [job]
    service = _make_service(api_client)

    generate_mock = AsyncMock(return_value=b"raw-image")
    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", generate_mock):
        results = await service.sync_jobs(all_active=True)

    assert len(results) == 1
    assert results[0].generated == 4  # 2 subjects x 2 images
    assert results[0].failed == 0
    assert generate_mock.await_count == 4

    # Every generated image was uploaded and registered with the expected payload.
    assert service.storage.upload_from_bytes.call_count == 4  # ty: ignore[missing-attribute]
    payload = api_client.register_image.call_args.args[0]
    assert payload.source_name == "gemini"
    assert payload.storage_path.startswith("gemini/")
    assert payload.title in {"a fox", "a heron"}
    assert payload.sync_job_name == job.name
    assert payload.expires_at is None  # no retention configured


async def test_portrait_swaps_dimensions_and_sets_expiry() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    api_client.get_active_gemini_jobs.return_value = [_make_job(orientation="portrait", retention_days=7)]
    service = _make_service(api_client)

    generate_mock = AsyncMock(return_value=b"raw-image")
    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", generate_mock):
        await service.sync_jobs(all_active=True)

    # The prompt must carry the portrait flag into the Gemini call.
    prompt = generate_mock.call_args.args[1]
    assert prompt.is_portrait is True

    # The 1600x1200 landscape profile is swapped for portrait targets.
    process_args = api_client.process_image.call_args.args
    assert process_args[1:3] == (1200, 1600)

    payload = api_client.register_image.call_args.args[0]
    assert payload.is_portrait is True
    assert payload.expires_at is not None
    assert payload.expires_at > utcnow() + timedelta(days=6)


async def test_one_failed_generation_does_not_abort_the_batch() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    api_client.get_active_gemini_jobs.return_value = [_make_job(subjects=["bad", "good-1", "good-2"])]
    service = _make_service(api_client)

    generate_mock = AsyncMock(side_effect=[Exception("Gemini exploded"), b"raw", b"raw"])
    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", generate_mock):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 2
    assert results[0].failed == 1
    assert any("bad" in error for error in results[0].errors)
    assert api_client.register_image.await_count == 2


async def test_preset_load_failure_fails_job_but_continues_with_next() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    api_client.get_active_gemini_jobs.return_value = [_make_job(name="broken"), _make_job(name="healthy")]
    api_client.get_prompt_preset.side_effect = [Exception("preset gone"), preset]
    service = _make_service(api_client)

    generate_mock = AsyncMock(return_value=b"raw-image")
    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", generate_mock):
        results = await service.sync_jobs(all_active=True)

    assert [(r.job_name, r.generated, r.failed) for r in results] == [("broken", 0, 1), ("healthy", 1, 0)]
    assert "preset gone" in results[0].errors[0]


async def test_missing_prompt_blocks_fail_and_report_every_claimed_job() -> None:
    # The claim already advanced both schedules, so a block lookup failure
    # must still produce a run (and a report) for each job, not escape.
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    api_client.claim_due_gemini_jobs.return_value = [_make_job(name="one"), _make_job(name="two")]
    api_client.list_prompt_blocks.side_effect = RuntimeError("blocks endpoint down")
    service = _make_service(api_client)

    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", AsyncMock()):
        results = await service.sync_jobs()

    assert [(r.job_name, r.failed) for r in results] == [("one", 1), ("two", 1)]
    reports = [c.args[0] for c in api_client.report_sync_run.await_args_list]
    assert [(r.job_name, r.status) for r in reports] == [("one", "error"), ("two", "error")]
    assert "blocks endpoint down" in reports[0].error


async def test_preset_pointing_at_a_deleted_block_is_reported_by_role() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks[1:], preset)  # style block deleted
    api_client.claim_due_gemini_jobs.return_value = [_make_job()]
    service = _make_service(api_client)

    results = await service.sync_jobs()

    assert "missing style block" in results[0].errors[0]
    assert api_client.report_sync_run.await_args.args[0].status == "error"


def test_build_prompt_names_the_missing_block() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    with pytest.raises(ValueError, match="missing palette block"):
        build_prompt(preset, {b.id: b for b in blocks if b.kind != "palette"}, is_portrait=False)


async def test_api_key_is_unwrapped_only_at_the_gemini_call() -> None:
    blocks = _make_blocks()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset)
    api_client.get_active_gemini_jobs.return_value = [_make_job()]
    service = _make_service(api_client)

    assert "test-key" not in repr(service.gemini_config)
    generate_mock = AsyncMock(return_value=b"raw")
    with patch("inky_image_display_sync.gemini.sync_service.generate_image_bytes", generate_mock):
        await service.sync_jobs(all_active=True)
    assert generate_mock.call_args.args[0] == "test-key"
