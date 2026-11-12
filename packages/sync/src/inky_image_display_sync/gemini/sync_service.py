"""Gemini batch sync service.

For each active ``GeminiSyncJob``, iterates subjects x images_per_subject,
calls the Gemini image model with the job's prompt preset, asks the API to
resize the result, uploads to S3, and registers it via the Display API.
Mirrors the role of ``ImmichSyncService`` for an AI image source — share
only the cross-cutting helpers (``GeminiDisplayAPIClient``,
``S3StorageClient``, :mod:`inky_image_display_sync.jobs`) rather than a
generic pipeline, because the per-source logic differs enough that a forced
abstraction would obscure more than help.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from inky_image_display_shared.ai import RenderedPrompt, generate_image_bytes

from inky_image_display_sync.api_client import ImageRegisterPayload
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.jobs import expiry, report_run, run_claimed, target_dims
from inky_image_display_sync.storage import S3StorageClient, S3WriterConfig

if TYPE_CHECKING:
    import logging
    from datetime import datetime

    from inky_image_display_shared.schemas.responses import (
        GeminiSyncJobResponse,
        PromptBlockResponse,
        PromptPresetResponse,
    )

    from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient


@dataclass
class GeminiSyncResult:
    """Counters returned after running one Gemini sync job."""

    job_name: str
    generated: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class GeminiSyncService:
    """Run all active Gemini sync jobs."""

    def __init__(
        self,
        api_client: GeminiDisplayAPIClient,
        logger: logging.Logger,
        gemini_config: GeminiConnectionConfig | None = None,
        sync_config: GeminiSyncConfig | None = None,
        s3_config: S3WriterConfig | None = None,
    ) -> None:
        """Capture dependencies; configs default to environment-driven settings."""
        self.api_client = api_client
        self.logger = logger
        self.gemini_config = gemini_config or GeminiConnectionConfig()
        self.sync_config = sync_config or GeminiSyncConfig()
        self.storage = S3StorageClient(
            config=s3_config or S3WriterConfig(),
            logger=logger,
        )

    async def sync_jobs(self, all_active: bool = False) -> list[GeminiSyncResult]:
        """Fetch Gemini jobs and run each one in sequence, reporting each run.

        The default mode claims due jobs from the API (per-job schedule plus
        Run-now flags); ``all_active`` ignores the schedule and runs every
        active job (manual/debug invocations).
        """
        await self.storage.ensure_bucket_exists()
        if all_active:
            jobs = await self.api_client.get_active_gemini_jobs()
        else:
            jobs = await self.api_client.claim_due_gemini_jobs()
        if not jobs:
            self.logger.info("No %s Gemini sync jobs", "active" if all_active else "due")
            return []

        library = PromptLibrary(self.api_client)
        return await run_claimed(
            jobs,
            run_one=lambda job: self._run_job(job, library),
            on_error=lambda job, exc: GeminiSyncResult(job_name=job.name, failed=1, errors=[str(exc)]),
            report=self._report_run,
            logger=self.logger,
        )

    async def _report_run(self, job: GeminiSyncJobResponse, result: GeminiSyncResult, started_at: datetime) -> None:
        self.logger.info("Gemini job %s: generated=%d failed=%d", job.name, result.generated, result.failed)
        await report_run(
            self.api_client,
            job_type="gemini",
            job=job,
            started_at=started_at,
            errors=result.errors,
            detail=f"generated={result.generated} failed={result.failed}",
            images_added=result.generated,
        )

    async def _run_job(self, job: GeminiSyncJobResponse, library: PromptLibrary) -> GeminiSyncResult:
        preset = await self.api_client.get_prompt_preset(job.prompt_preset_id)
        result = GeminiSyncResult(job_name=job.name)
        try:
            profile = await self.api_client.get_device_profile(job.target_device_profile_id)
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"target device profile {job.target_device_profile_id} not found: {exc}")
            return result

        is_portrait = job.orientation == "portrait"
        target_width, target_height = target_dims(profile, is_portrait)
        prompt = build_prompt(preset, await library.blocks(), is_portrait)
        expires_at = expiry(job.retention_days)

        for subject in job.subjects:
            for _ in range(job.images_per_subject):
                try:
                    await self._generate_one(
                        job=job,
                        subject=subject,
                        prompt=prompt,
                        model=preset.model_name,
                        target_width=target_width,
                        target_height=target_height,
                        expires_at=expires_at,
                    )
                    result.generated += 1
                except Exception as exc:
                    self.logger.exception("Generation failed for job %s subject %r", job.name, subject)
                    result.failed += 1
                    result.errors.append(f"{subject}: {exc}")
        return result

    async def _generate_one(  # noqa: PLR0913
        self,
        *,
        job: GeminiSyncJobResponse,
        subject: str,
        prompt: RenderedPrompt,
        model: str,
        target_width: int,
        target_height: int,
        expires_at: datetime | None,
    ) -> None:
        raw_bytes = await generate_image_bytes(
            self.gemini_config.api_key.get_secret_value(),
            prompt,
            subject,
            model=model,
        )
        # Generated images are larger than the panel; ask the API to resize +
        # center-crop so all sync paths share the same processing endpoint.
        jpeg_bytes = await self.api_client.process_image(
            raw_bytes,
            target_width,
            target_height,
            upscale=True,
        )
        self.logger.info("Generated %r with %s", subject, model)

        image_uuid = uuid4()
        storage_path = f"{self.sync_config.storage_prefix}/{image_uuid}.jpg"
        await self.storage.upload_from_bytes(
            object_path=storage_path,
            data=jpeg_bytes,
            content_type="image/jpeg",
        )

        await self.api_client.register_image(
            ImageRegisterPayload(
                source_name="gemini",
                source_id=str(image_uuid),
                sync_job_name=job.name,
                storage_path=storage_path,
                title=subject,
                description=f"AI-generated: {subject}",
                tags="gemini,ai",
                original_width=target_width,
                original_height=target_height,
                is_portrait=job.orientation == "portrait",
                expires_at=expires_at,
            )
        )


class PromptLibrary:
    """Prompt blocks fetched at most once per run, on first use.

    Fetched lazily inside a job rather than up front so a failing lookup
    fails the jobs that need it (and gets reported) instead of escaping the
    run after the claim has already advanced every job's schedule.
    """

    def __init__(self, api_client: GeminiDisplayAPIClient) -> None:
        """Bind to the client the blocks will be fetched from."""
        self._api_client = api_client
        self._blocks: dict[UUID, PromptBlockResponse] | None = None

    async def blocks(self) -> dict[UUID, PromptBlockResponse]:
        """Return every block by id, fetching on the first call only."""
        if self._blocks is None:
            self._blocks = {b.id: b for b in await self._api_client.list_prompt_blocks()}
        return self._blocks


def build_prompt(
    preset: PromptPresetResponse,
    blocks_by_id: dict[UUID, PromptBlockResponse],
    is_portrait: bool,
) -> RenderedPrompt:
    """Assemble the image prompt from a preset's blocks.

    Shared with the display worker, whose illustrations use the same
    preset machinery.

    Raises:
        ValueError: If the preset references a block that no longer exists —
            a bare ``KeyError`` would surface in the run report as just a UUID.

    """

    def text(role: str, block_id: UUID) -> str:
        block = blocks_by_id.get(block_id)
        if block is None:
            raise ValueError(f"preset {preset.name!r} references missing {role} block {block_id}")
        return block.text

    return RenderedPrompt(
        style=text("style", preset.style_block_id),
        palette=text("palette", preset.palette_block_id),
        legibility=text("legibility", preset.legibility_block_id),
        composition=text("composition", preset.composition_block_id),
        background=text("background", preset.background_block_id),
        is_portrait=is_portrait,
    )
