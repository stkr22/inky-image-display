"""Calibre bookshelf sync service.

For each active ``CalibreSyncJob``: read the (cached) Calibre catalog, filter
and sample books according to the job, generate an image per set, have the API
resize it, upload to S3 and register it via the Display API. Mirrors the role
of ``GeminiSyncService`` for a book library, sharing its API client and the S3
writer rather than a forced common pipeline.

Two things here that the other sources do not need:

*Verification.* Image models render spine lettering convincingly but not
reliably — a dropped letter, an author on the wrong book, a seventh book on a
six-book shelf. Since the exact strings are known in advance, a shelf is read
back and regenerated on mismatch. After ``max_attempts`` the last attempt is
kept anyway: a shelf with one wrong word still beats a blank panel.

*Refusal handling.* Two different failures share one symptom. Any generation
can fail sporadically, which a retry clears; but a cover that is a photograph
of a real identifiable person is refused every single time, and only dropping
the reference image gets past it. Retry first, then fall back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from inky_image_display_shared.ai import (
    GeminiGenerationError,
    generate_image_bytes,
    spines_match,
    transcribe_spines,
)
from inky_image_display_shared.time import utcnow

from inky_image_display_sync.api_client import ImageRegisterPayload, SyncRunReportPayload
from inky_image_display_sync.calibre.client import BookFilter, CalibreClient, select_books
from inky_image_display_sync.calibre.config import CalibreConnectionConfig
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.gemini.sync_service import build_prompt
from inky_image_display_sync.immich.config import S3WriterConfig
from inky_image_display_sync.immich.storage import S3StorageClient

if TYPE_CHECKING:
    import logging

    from inky_image_display_shared.ai import RenderedPrompt

    from inky_image_display_sync.calibre.api_client import CalibreDisplayAPIClient, CalibreSyncJobItem
    from inky_image_display_sync.calibre.client import CalibreBook
    from inky_image_display_sync.gemini.api_client import PromptPresetItem

MODE_HERO = "hero"


@dataclass
class CalibreSyncResult:
    """Counters returned after running one bookshelf job."""

    job_name: str
    generated: int = 0
    failed: int = 0
    unverified: int = 0
    errors: list[str] = field(default_factory=list)


class CalibreSyncService:
    """Run all due (or all active) Calibre bookshelf jobs."""

    def __init__(  # noqa: PLR0913, PLR0917 — five injectable configs, all defaulted
        self,
        api_client: CalibreDisplayAPIClient,
        logger: logging.Logger,
        gemini_config: GeminiConnectionConfig | None = None,
        sync_config: GeminiSyncConfig | None = None,
        s3_config: S3WriterConfig | None = None,
        calibre_config: CalibreConnectionConfig | None = None,
    ) -> None:
        """Capture dependencies; configs default to environment-driven settings."""
        self.api_client = api_client
        self.logger = logger
        self.gemini_config = gemini_config or GeminiConnectionConfig()
        self.sync_config = sync_config or GeminiSyncConfig()
        self.storage = S3StorageClient(config=s3_config or S3WriterConfig(), logger=logger)
        self.calibre = CalibreClient(calibre_config or CalibreConnectionConfig(), logger)

    async def sync_jobs(self, all_active: bool = False) -> list[CalibreSyncResult]:
        """Fetch bookshelf jobs and run each one in sequence, reporting each run."""
        self.storage.ensure_bucket_exists()
        if all_active:
            jobs = await self.api_client.get_active_calibre_jobs()
        else:
            jobs = await self.api_client.claim_due_calibre_jobs()
        if not jobs:
            self.logger.info("No %s Calibre jobs", "active" if all_active else "due")
            return []

        # Cache blocks so we only fetch them once per run.
        blocks_by_id = {b.id: b for b in await self.api_client.list_prompt_blocks()}

        results: list[CalibreSyncResult] = []
        for job in jobs:
            started_at = utcnow()
            try:
                preset = await self.api_client.get_prompt_preset(job.prompt_preset_id)
            except Exception as exc:
                self.logger.error("Failed to load preset for job %s: %s", job.name, exc)
                result = CalibreSyncResult(job_name=job.name, failed=1, errors=[str(exc)])
            else:
                result = await self._run_job(job, preset, blocks_by_id)
            results.append(result)
            self.logger.info(
                "Calibre job %s: generated=%d failed=%d unverified=%d",
                job.name,
                result.generated,
                result.failed,
                result.unverified,
            )
            await self._report_run(job, result, started_at)
        return results

    async def _report_run(self, job: CalibreSyncJobItem, result: CalibreSyncResult, started_at: datetime) -> None:
        """POST the run outcome so the UI can show last-run status per job."""
        detail = f"generated={result.generated} failed={result.failed}"
        if result.unverified:
            detail += f" unverified={result.unverified}"
        await self.api_client.report_sync_run(
            SyncRunReportPayload(
                job_type="calibre",
                job_id=job.id,
                job_name=job.name,
                status="error" if result.errors else "success",
                started_at=started_at,
                finished_at=utcnow(),
                images_added=result.generated,
                detail=detail,
                error="; ".join(result.errors[:3]) if result.errors else None,
            )
        )

    async def _run_job(
        self,
        job: CalibreSyncJobItem,
        preset: PromptPresetItem,
        blocks_by_id: dict,
    ) -> CalibreSyncResult:
        result = CalibreSyncResult(job_name=job.name)
        try:
            profile = await self.api_client.get_device_profile(job.target_device_profile_id)
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"target device profile {job.target_device_profile_id} not found: {exc}")
            return result

        try:
            catalog = await self.calibre.fetch_catalog()
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"calibre catalog: {exc}")
            return result

        book_filter = BookFilter(
            tags=job.tags,
            languages=job.languages,
            series=job.series,
            authors=job.authors,
            min_rating=job.min_rating,
        )
        # A hero shows one book; a shelf shows several. Both draw from the same
        # filtered pool, one draw per image so a run doesn't repeat a book.
        per_image = 1 if job.mode == MODE_HERO else job.books_per_shelf
        wanted = per_image * job.images_per_run
        picked = select_books(catalog, wanted, book_filter)
        if not picked:
            result.failed += 1
            result.errors.append(f"no books in the {len(catalog)}-book catalog match this job's filter")
            return result

        # Heroes are portrait (a cover), shelves landscape (a row of spines).
        is_portrait = job.mode == MODE_HERO
        target_width, target_height = (
            (profile.height, profile.width) if is_portrait else (profile.width, profile.height)
        )
        prompt = build_prompt(preset, blocks_by_id, is_portrait)
        expires_at = (
            datetime.now() + timedelta(days=job.retention_days)
            if job.retention_days is not None and job.retention_days > 0
            else None
        )

        for start in range(0, len(picked), per_image):
            books = picked[start : start + per_image]
            if len(books) < per_image:
                # The filter ran dry mid-run; a short shelf isn't worth a call.
                break
            try:
                await self._generate_one(
                    job=job,
                    books=books,
                    prompt=prompt,
                    model=preset.model_name,
                    target_width=target_width,
                    target_height=target_height,
                    is_portrait=is_portrait,
                    expires_at=expires_at,
                    result=result,
                )
                result.generated += 1
            except Exception as exc:
                self.logger.exception("Generation failed for job %s", job.name)
                result.failed += 1
                result.errors.append(f"{books[0].title}: {exc}")
        return result

    async def _generate_one(  # noqa: PLR0913 — one image needs all of its context
        self,
        *,
        job: CalibreSyncJobItem,
        books: list[CalibreBook],
        prompt: RenderedPrompt,
        model: str,
        target_width: int,
        target_height: int,
        is_portrait: bool,
        expires_at: datetime | None,
        result: CalibreSyncResult,
    ) -> None:
        """Generate, verify, process and register one bookshelf image."""
        subject = _subject_for(job.mode, books)
        cover = await self._cover_for(job, books)

        raw, verified = await self._generate_verified(
            job=job,
            books=books,
            prompt=prompt,
            subject=subject,
            model=model,
            cover=cover,
        )
        if not verified:
            result.unverified += 1

        jpeg_bytes = await self.api_client.process_image(raw, target_width, target_height, upscale=True)

        image_uuid = uuid4()
        storage_path = f"{self.sync_config.storage_prefix}/calibre/{image_uuid}.jpg"
        self.storage.upload_from_bytes(object_path=storage_path, data=jpeg_bytes, content_type="image/jpeg")

        titles = ", ".join(b.short_title() for b in books)
        await self.api_client.register_image(
            ImageRegisterPayload(
                source_name="calibre",
                # One book per hero, so its id dedupes; a shelf is a fresh
                # combination each run and has no stable identity to reuse.
                source_id=f"calibre:{books[0].book_id}" if job.mode == MODE_HERO else str(image_uuid),
                sync_job_name=job.name,
                storage_path=storage_path,
                title=books[0].title if job.mode == MODE_HERO else f"Bookshelf: {titles}",
                description=books[0].description if job.mode == MODE_HERO else titles,
                author=books[0].author if job.mode == MODE_HERO else None,
                tags=f"calibre,books,{job.mode}",
                original_width=target_width,
                original_height=target_height,
                is_portrait=is_portrait,
                expires_at=expires_at,
            )
        )

    async def _generate_verified(  # noqa: PLR0913 — keyword-only generation context
        self,
        *,
        job: CalibreSyncJobItem,
        books: list[CalibreBook],
        prompt: RenderedPrompt,
        subject: str,
        model: str,
        cover: bytes | None,
    ) -> tuple[bytes, bool]:
        """Generate until the spines read back correctly, or attempts run out.

        Returns the image and whether it passed. The last attempt is returned
        even unverified — a shelf with one wrong word beats an empty panel, and
        the caller counts it so the run report stays honest.
        """
        expected = [(b.short_title(), b.author or "") for b in books]
        verify = job.verify_spines and job.mode != MODE_HERO
        last: bytes | None = None

        for attempt in range(1, job.max_attempts + 1):
            try:
                last = await generate_image_bytes(
                    self.gemini_config.api_key,
                    prompt,
                    subject,
                    model=model,
                    reference_image=cover,
                )
            except GeminiGenerationError as exc:
                if cover is not None:
                    # Refusals on a cover are permanent, so stop paying for
                    # retries with it attached and let the prompt stand alone.
                    self.logger.warning("Job %s: dropping cover reference after %s", job.name, exc)
                    cover = None
                if attempt == job.max_attempts:
                    raise
                continue

            if not verify:
                return last, True
            if await self._spines_ok(job, last, expected):
                return last, True
            self.logger.info("Job %s: spine check failed on attempt %d/%d", job.name, attempt, job.max_attempts)

        if last is None:
            raise GeminiGenerationError(f"no image after {job.max_attempts} attempts")
        self.logger.warning("Job %s: keeping unverified image after %d attempts", job.name, job.max_attempts)
        return last, False

    async def _spines_ok(self, job: CalibreSyncJobItem, image: bytes, expected: list[tuple[str, str]]) -> bool:
        """Read the spines back; a failed check is not a failed generation."""
        try:
            readings = await transcribe_spines(self.gemini_config.api_key, image)
        except Exception:
            # Verification is a safety net, not a gate — if the reader is
            # unavailable, keep the image rather than burning every attempt.
            self.logger.warning("Job %s: spine transcription unavailable, accepting image", job.name, exc_info=True)
            return True
        return spines_match(expected, readings)

    async def _cover_for(self, job: CalibreSyncJobItem, books: list[CalibreBook]) -> bytes | None:
        """Fetch the hero book's cover; shelves are generated from text alone."""
        if job.mode != MODE_HERO:
            return None
        try:
            return await self.calibre.fetch_cover(books[0].book_id)
        except Exception:
            # A missing cover degrades the hero to a text-only interpretation
            # rather than dropping the book entirely.
            self.logger.warning("Job %s: no cover for book %d", job.name, books[0].book_id, exc_info=True)
            return None


def _subject_for(mode: str, books: list[CalibreBook]) -> str:
    """Render the ``{subject}`` the preset's composition block expects."""
    if mode == MODE_HERO:
        return books[0].as_subject()
    return "\n".join(f'- Title "{b.short_title()}" — author "{b.author or "Unknown"}"' for b in books)
