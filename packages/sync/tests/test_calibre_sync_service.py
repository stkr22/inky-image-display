"""Tests for the Calibre bookshelf sync service.

Gemini, Calibre and the Display API are mocked at the client boundary. What is
pinned here is the orchestration that is unique to this source and that no
other job type exercises: the spine verify-and-retry loop, the difference
between a sporadic failure (retry) and a permanent cover refusal (drop the
reference and carry on), and the hero/shelf split in selection and registration.
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from inky_image_display_shared.ai import GeminiGenerationError, SpineReading
from inky_image_display_shared.schemas.responses import (
    CalibreSyncJobResponse,
    DeviceProfileResponse,
    PromptBlockResponse,
    PromptPresetResponse,
)
from inky_image_display_shared.time import utcnow
from inky_image_display_sync.calibre.api_client import CalibreDisplayAPIClient
from inky_image_display_sync.calibre.client import CalibreBook
from inky_image_display_sync.calibre.config import CalibreConnectionConfig
from inky_image_display_sync.calibre.sync_service import CalibreSyncService, books_per_image, downscale_cover
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.storage import S3WriterConfig
from PIL import Image

_BLOCK_KINDS = ("style", "palette", "legibility", "composition", "background")
_NOW = utcnow()

_SERVICE = "inky_image_display_sync.calibre.sync_service"


def _make_blocks() -> list[PromptBlockResponse]:
    return [
        PromptBlockResponse(
            id=uuid4(),
            kind=kind,
            name=f"{kind}-default",
            text=f"{kind} {{subject}}",
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
        name="bookshelf_shelf",
        style_block_id=ids["style"],
        palette_block_id=ids["palette"],
        legibility_block_id=ids["legibility"],
        composition_block_id=ids["composition"],
        background_block_id=ids["background"],
        model_name="gemini-test-image",
        is_default=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_job(mode: str = "shelf", **overrides) -> CalibreSyncJobResponse:
    fields = {
        "id": uuid4(),
        "name": "test-shelf",
        "is_active": True,
        "mode": mode,
        "target_device_profile_id": uuid4(),
        "prompt_preset_id": uuid4(),
        "tags": [],
        "languages": [],
        "authors": [],
        "books_per_shelf": 2,
        "shelf_rows": 3,
        "avoid_repeats": True,
        "images_per_run": 1,
        "retention_days": None,
        "verify_spines": True,
        "max_attempts": 3,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    fields.update(overrides)
    return CalibreSyncJobResponse.model_validate(fields)


def _books(count: int = 4) -> list[CalibreBook]:
    return [
        CalibreBook(book_id=100 + i, title=f"Book {i}", authors=[f"Author {i}"], tags=["Fantasy"], language="deu")
        for i in range(count)
    ]


def _jpeg(width: int, height: int) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), "red").save(out, format="JPEG")
    return out.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as image:
        return image.size


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
    service.storage = AsyncMock()
    service.calibre = AsyncMock()
    service.calibre.fetch_catalog.return_value = catalog if catalog is not None else _books()
    service.calibre.fetch_cover.return_value = _jpeg(600, 900)
    return service


def _api_client(
    blocks: list[PromptBlockResponse], preset: PromptPresetResponse, job: CalibreSyncJobResponse
) -> AsyncMock:
    api_client = AsyncMock(spec=CalibreDisplayAPIClient)
    api_client.list_prompt_blocks.return_value = blocks
    api_client.get_prompt_preset.return_value = preset
    api_client.get_device_profile.return_value = DeviceProfileResponse(
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
    api_client.process_image.return_value = b"processed-jpeg"
    api_client.get_active_calibre_jobs.return_value = [job]
    api_client.get_used_book_ids.return_value = set()
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
    assert _size(generate.await_args.kwargs["reference_image"]) == (600, 900)  # ty: ignore[missing-union-attribute]
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
    assert generate.await_args_list[0].kwargs["reference_image"] is not None
    assert generate.await_args_list[1].kwargs["reference_image"] is None


async def test_missing_cover_degrades_hero_instead_of_dropping_the_book() -> None:
    blocks, job = _make_blocks(), _make_job(mode="hero")
    preset = _make_preset(blocks)
    api_client = _api_client(blocks, preset, job)
    service = _make_service(api_client, _books(2))
    service.calibre.fetch_cover.side_effect = RuntimeError("404")  # ty: ignore[missing-attribute]

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 1
    assert generate.await_args.kwargs["reference_image"] is None  # ty: ignore[missing-union-attribute]


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


async def test_registered_image_records_its_books_in_order() -> None:
    blocks, job = _make_blocks(), _make_job(verify_spines=False)
    api_client = _api_client(blocks, _make_preset(blocks), job)
    catalog = _books(2)
    service = _make_service(api_client, catalog)

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock(return_value=b"raw")):
        await service.sync_jobs(all_active=True)

    payload = api_client.register_image.call_args.args[0]
    assert [(b.book_id, b.title) for b in payload.books] == [(b.book_id, b.title) for b in catalog]


async def test_books_already_on_display_are_not_picked_again() -> None:
    blocks, job = _make_blocks(), _make_job(verify_spines=False)
    api_client = _api_client(blocks, _make_preset(blocks), job)
    api_client.get_used_book_ids.return_value = {100, 101}
    service = _make_service(api_client, _books(4))

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock(return_value=b"raw")):
        await service.sync_jobs(all_active=True)

    shown = {b.book_id for b in api_client.register_image.call_args.args[0].books}
    assert shown == {102, 103}


async def test_repeats_are_allowed_when_the_job_opts_out() -> None:
    blocks, job = _make_blocks(), _make_job(verify_spines=False, avoid_repeats=False)
    api_client = _api_client(blocks, _make_preset(blocks), job)
    api_client.get_used_book_ids.return_value = {100, 101}
    service = _make_service(api_client, _books(2))

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock(return_value=b"raw")):
        results = await service.sync_jobs(all_active=True)

    api_client.get_used_book_ids.assert_not_awaited()
    assert results[0].generated == 1


async def test_run_says_so_when_every_matching_book_is_in_use() -> None:
    blocks, job = _make_blocks(), _make_job()
    api_client = _api_client(blocks, _make_preset(blocks), job)
    api_client.get_used_book_ids.return_value = {100, 101}
    service = _make_service(api_client, _books(2))

    generate = AsyncMock()
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    generate.assert_not_awaited()
    assert results[0].failed == 1
    assert "already on display" in results[0].errors[0]


async def test_failed_lookup_of_used_books_does_not_generate_blindly() -> None:
    blocks, job = _make_blocks(), _make_job()
    api_client = _api_client(blocks, _make_preset(blocks), job)
    api_client.get_used_book_ids.side_effect = RuntimeError("api down")
    service = _make_service(api_client, _books(2))

    generate = AsyncMock()
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    generate.assert_not_awaited()
    assert "api down" in results[0].errors[0]


async def test_bookcase_is_portrait_and_lays_books_out_shelf_by_shelf() -> None:
    blocks = _make_blocks()
    job = _make_job("bookcase", books_per_shelf=2, shelf_rows=2, verify_spines=False)
    api_client = _api_client(blocks, _make_preset(blocks), job)
    catalog = _books(4)
    service = _make_service(api_client, catalog)

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    assert results[0].generated == 1
    payload = api_client.register_image.call_args.args[0]
    assert payload.is_portrait is True
    assert len(payload.books) == 4
    subject = generate.call_args.args[2]
    assert subject.index("Shelf 1 of 2 (top)") < subject.index("Shelf 2 of 2")
    # Each shelf holds exactly its own slice of the books.
    first_shelf, second_shelf = subject.split("Shelf 2 of 2")
    assert all(f'"{b.title}"' in first_shelf for b in payload.books[:2])
    assert all(f'"{b.title}"' in second_shelf for b in payload.books[2:])


async def test_incomplete_bookcase_is_not_generated() -> None:
    # Three books cannot fill a 2x2 case; a half-empty case is not worth a call.
    blocks = _make_blocks()
    job = _make_job("bookcase", books_per_shelf=2, shelf_rows=2, verify_spines=False)
    api_client = _api_client(blocks, _make_preset(blocks), job)
    service = _make_service(api_client, _books(3))

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        results = await service.sync_jobs(all_active=True)

    generate.assert_not_awaited()
    assert results[0].generated == 0


async def test_hero_cover_is_downscaled_before_it_reaches_gemini() -> None:
    blocks, job = _make_blocks(), _make_job(mode="hero")
    api_client = _api_client(blocks, _make_preset(blocks), job)
    service = _make_service(api_client, _books(1))
    service.calibre.fetch_cover.return_value = _jpeg(2000, 3000)  # ty: ignore[missing-attribute]

    generate = AsyncMock(return_value=b"raw")
    with patch(f"{_SERVICE}.generate_image_bytes", generate):
        await service.sync_jobs(all_active=True)

    assert _size(generate.await_args.kwargs["reference_image"]) == (683, 1024)  # ty: ignore[missing-union-attribute]


def test_downscale_reencodes_non_jpeg_covers() -> None:
    out = BytesIO()
    Image.new("RGBA", (300, 200)).save(out, format="PNG")
    with Image.open(BytesIO(downscale_cover(out.getvalue()))) as image:
        assert (image.format, image.size) == ("JPEG", (300, 200))


async def test_preset_load_failure_after_claim_still_reports_each_job() -> None:
    blocks = _make_blocks()
    jobs = [_make_job(name="one"), _make_job(name="two")]
    api_client = _api_client(blocks, _make_preset(blocks), jobs[0])
    api_client.claim_due_calibre_jobs.return_value = jobs
    api_client.list_prompt_blocks.side_effect = RuntimeError("blocks down")
    service = _make_service(api_client, _books(2))

    with patch(f"{_SERVICE}.generate_image_bytes", AsyncMock()):
        results = await service.sync_jobs()

    assert [r.failed for r in results] == [1, 1]
    reports = [c.args[0] for c in api_client.report_sync_run.await_args_list]
    assert [(r.job_name, r.status) for r in reports] == [("one", "error"), ("two", "error")]


def test_bookcase_counts_every_shelf_row() -> None:
    assert books_per_image(_make_job("bookcase", books_per_shelf=4, shelf_rows=3)) == 12
    assert books_per_image(_make_job("shelf", books_per_shelf=4, shelf_rows=3)) == 4
    assert books_per_image(_make_job("hero", books_per_shelf=4, shelf_rows=3)) == 1


def test_injected_calibre_client_is_kept() -> None:
    shared = MagicMock()
    service = CalibreSyncService(
        api_client=AsyncMock(spec=CalibreDisplayAPIClient),
        logger=MagicMock(),
        gemini_config=GeminiConnectionConfig(api_key="k"),
        s3_config=S3WriterConfig(endpoint="localhost:9000", access_key="k", secret_key="s"),
        calibre=shared,
    )
    assert service.calibre is shared
