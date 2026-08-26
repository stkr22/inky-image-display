"""Tests for the Calibre bookshelf sync service.

Gemini, Calibre and the Display API are mocked at the client boundary. What is
pinned here is the orchestration that is unique to this source and that no
other job type exercises: the spine verify-and-retry loop, the difference
between a sporadic failure (retry) and a permanent cover refusal (drop the
reference and carry on), and the hero/shelf split in selection and registration.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from inky_image_display_shared.ai import GeminiGenerationError, SpineReading
from inky_image_display_sync.api_client import DeviceProfileItem
from inky_image_display_sync.calibre.api_client import CalibreDisplayAPIClient, CalibreSyncJobItem
from inky_image_display_sync.calibre.client import CalibreBook
from inky_image_display_sync.calibre.config import CalibreConnectionConfig
from inky_image_display_sync.calibre.sync_service import CalibreSyncService
from inky_image_display_sync.gemini.api_client import PromptBlockItem, PromptPresetItem
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.immich.config import S3WriterConfig

_BLOCK_KINDS = ("style", "palette", "legibility", "composition", "background")

_SERVICE = "inky_image_display_sync.calibre.sync_service"


def _make_blocks() -> list[PromptBlockItem]:
    return [
        PromptBlockItem(id=uuid4(), kind=kind, name=f"{kind}-default", text=f"{kind} {{subject}}", is_default=True)
        for kind in _BLOCK_KINDS
    ]


def _make_preset(blocks: list[PromptBlockItem]) -> PromptPresetItem:
    ids = {b.kind: b.id for b in blocks}
    return PromptPresetItem(
        id=uuid4(),
        name="bookshelf_shelf",
        style_block_id=ids["style"],
        palette_block_id=ids["palette"],
        legibility_block_id=ids["legibility"],
        composition_block_id=ids["composition"],
        background_block_id=ids["background"],
        model_name="gemini-test-image",
        is_default=False,
    )


def _make_job(mode: str = "shelf", **overrides) -> CalibreSyncJobItem:
    fields = {
        "id": uuid4(),
        "name": "test-shelf",
        "is_active": True,
        "mode": mode,
        "target_device_profile_id": uuid4(),
        "prompt_preset_id": uuid4(),
        "tags": [],
        "languages": [],
        "series": [],
        "authors": [],
        "min_rating": None,
        "books_per_shelf": 2,
        "images_per_run": 1,
        "retention_days": None,
        "verify_spines": True,
        "max_attempts": 3,
    }
    fields.update(overrides)
    return CalibreSyncJobItem(**fields)


def _books(count: int = 4) -> list[CalibreBook]:
    return [
        CalibreBook(book_id=100 + i, title=f"Book {i}", author=f"Author {i}", tags=["Fantasy"], language="deu")
        for i in range(count)
    ]


def _readings(books: list[CalibreBook]) -> list[SpineReading]:
    return [SpineReading(title=b.title, author=b.author or "") for b in books]


def _make_service(api_client: AsyncMock, catalog: list[CalibreBook] | None = None) -> CalibreSyncService:
    service = CalibreSyncService(
        api_client=api_client,
        logger=MagicMock(),
        gemini_config=GeminiConnectionConfig(api_key="test-key"),
        sync_config=GeminiSyncConfig(storage_prefix="ai"),
        s3_config=S3WriterConfig(
            endpoint="localhost:9000",
            bucket="test-bucket",
            secure=False,
            access_key="k",
            secret_key="s",
        ),
        calibre_config=CalibreConnectionConfig(base_url="http://calibre.invalid"),
    )
    service.storage = MagicMock()
    service.calibre = AsyncMock()
    service.calibre.fetch_catalog.return_value = catalog if catalog is not None else _books()
    service.calibre.fetch_cover.return_value = b"cover-bytes"
    return service


def _api_client(blocks: list[PromptBlockItem], preset: PromptPresetItem, job: CalibreSyncJobItem) -> AsyncMock:
    api_client = AsyncMock(spec=CalibreDisplayAPIClient)
    api_client.list_prompt_blocks.return_value = blocks
    api_client.get_prompt_preset.return_value = preset
    api_client.get_device_profile.return_value = DeviceProfileItem(
        id=uuid4(),
        key="inky_impression_13_spectra6",
        name="Test profile",
        width=1600,
        height=1200,
        model="test-model",
        is_default=True,
    )
    api_client.process_image.return_value = b"processed-jpeg"
    api_client.get_active_calibre_jobs.return_value = [job]
    return api_client


async def test_no_active_jobs_returns_empty() -> None:
    api_client = AsyncMock(spec=CalibreDisplayAPIClient)
    api_client.get_active_calibre_jobs.return_value = []
    service = _make_service(api_client)
    assert await service.sync_jobs(all_active=True) == []


async def test_shelf_passes_verification_on_first_attempt() -> None:
    blocks, job = _make_blocks(), _make_job()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    catalog = _books(2)
    service = _make_service(api_client, catalog)

    generate = AsyncMock(return_value=b"raw")
    with (
        patch(f"{_SERVICE}.generate_image_bytes", generate),
        patch(f"{_SERVICE}.transcribe_spines", AsyncMock(return_value=_readings(catalog))),
    ):
        results = await service.sync_jobs(all_active=True)

    assert (results[0].generated, results[0].failed, results[0].unverified) == (1, 0, 0)
    assert generate.await_count == 1
    payload = api_client.register_image.call_args.args[0]
    assert payload.source_name == "calibre"
    assert payload.title.startswith("Bookshelf:")
    assert payload.is_portrait is False


async def test_shelf_regenerates_until_spines_read_back_correctly() -> None:
    blocks, job = _make_blocks(), _make_job()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    catalog = _books(2)
    service = _make_service(api_client, catalog)

    wrong = [SpineReading(title="Boook 0", author="Author 0"), SpineReading(title="Book 1", author="Author 1")]
    transcribe = AsyncMock(side_effect=[wrong, _readings(catalog)])
    generate = AsyncMock(return_value=b"raw")
    with (
        patch(f"{_SERVICE}.generate_image_bytes", generate),
        patch(f"{_SERVICE}.transcribe_spines", transcribe),
    ):
        results = await service.sync_jobs(all_active=True)

    assert generate.await_count == 2
    assert (results[0].generated, results[0].unverified) == (1, 0)


async def test_unverifiable_shelf_is_kept_but_counted() -> None:
    # A shelf with one wrong word still beats a blank panel, so the last
    # attempt is registered — but the run report has to say so.
    blocks, job = _make_blocks(), _make_job(max_attempts=2)
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))

    wrong = [SpineReading(title="Nope", author="Nobody")]
    generate = AsyncMock(return_value=b"raw")
    with (
        patch(f"{_SERVICE}.generate_image_bytes", generate),
        patch(f"{_SERVICE}.transcribe_spines", AsyncMock(return_value=wrong)),
    ):
        results = await service.sync_jobs(all_active=True)

    assert generate.await_count == 2
    assert (results[0].generated, results[0].unverified) == (1, 1)
    assert api_client.register_image.await_count == 1


async def test_verification_disabled_skips_the_readback() -> None:
    blocks, job = _make_blocks(), _make_job(verify_spines=False)
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))

    transcribe = AsyncMock()
    with (
        patch(f"{_SERVICE}.generate_image_bytes", AsyncMock(return_value=b"raw")),
        patch(f"{_SERVICE}.transcribe_spines", transcribe),
    ):
        results = await service.sync_jobs(all_active=True)

    transcribe.assert_not_awaited()
    assert results[0].generated == 1


async def test_transcription_outage_accepts_the_image() -> None:
    # Verification is a safety net; if the reader is down, burning every
    # attempt and dropping the shelf would be worse than keeping it.
    blocks, job = _make_blocks(), _make_job()
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))

    generate = AsyncMock(return_value=b"raw")
    with (
        patch(f"{_SERVICE}.generate_image_bytes", generate),
        patch(f"{_SERVICE}.transcribe_spines", AsyncMock(side_effect=RuntimeError("vision down"))),
    ):
        results = await service.sync_jobs(all_active=True)

    assert generate.await_count == 1
    assert (results[0].generated, results[0].unverified) == (1, 0)


async def test_hero_sends_the_cover_and_registers_portrait() -> None:
    blocks, job = _make_blocks(), _make_job(mode="hero")
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    catalog = _books(3)
    service = _make_service(api_client, catalog)

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 1
    assert generate.await_args.kwargs["reference_image"] == b"cover-bytes"  # ty: ignore[unresolved-attribute]
    payload = api_client.register_image.call_args.args[0]
    assert payload.is_portrait is True
    # Portrait swaps the profile's landscape-native dimensions.
    assert (payload.original_width, payload.original_height) == (1200, 1600)
    # One book per hero, so its id dedupes future runs.
    assert payload.source_id.startswith("calibre:")


async def test_hero_falls_back_to_text_only_when_the_cover_is_refused() -> None:
    # Covers that are photographs of real people are refused every time, so
    # retrying with the same reference just burns quota.
    blocks, job = _make_blocks(), _make_job(mode="hero")
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))

    generate = AsyncMock(side_effect=[GeminiGenerationError("IMAGE_OTHER"), b"raw"])
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 1
    assert generate.await_args_list[0].kwargs["reference_image"] == b"cover-bytes"
    assert generate.await_args_list[1].kwargs["reference_image"] is None


async def test_missing_cover_degrades_hero_instead_of_dropping_the_book() -> None:
    blocks, job = _make_blocks(), _make_job(mode="hero")
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))
    service.calibre.fetch_cover.side_effect = RuntimeError("404")  # ty: ignore[unresolved-attribute]

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 1
    assert generate.await_args.kwargs["reference_image"] is None  # ty: ignore[unresolved-attribute]


async def test_filter_that_matches_nothing_reports_an_error() -> None:
    blocks, job = _make_blocks(), _make_job(tags=["Nonexistent"])
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(4))

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock()) as generate:
        results = await service.sync_jobs(all_active=True)

    generate.assert_not_awaited()
    assert results[0].generated == 0
    assert "match this job's filter" in results[0].errors[0]


async def test_run_is_reported_with_the_calibre_job_type() -> None:
    blocks, job = _make_blocks(), _make_job(verify_spines=False)
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock(return_value=b"raw")):
        await service.sync_jobs(all_active=True)

    report = api_client.report_sync_run.call_args.args[0]
    assert report.job_type == "calibre"
    assert report.status == "success"
    assert report.images_added == 1
