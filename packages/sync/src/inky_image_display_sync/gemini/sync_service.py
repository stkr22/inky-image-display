"""Gemini batch sync service.

For each active ``GeminiSyncJob``, iterates subjects x images_per_subject,
calls the Gemini image model with the job's prompt preset, uploads the result
to S3, and registers it via the Display API. Mirrors the role of
``ImmichSyncService`` for an AI image source — share only the cross-cutting
utilities (``ColorProfileAnalyzer``, ``ImageProcessor``, ``GeminiDisplayAPIClient``,
``S3StorageClient``) rather than a generic pipeline, because the per-source
logic differs enough that a forced abstraction would obscure more than help.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from inky_image_display_shared.ai import RenderedPrompt, generate_image_bytes
from inky_image_display_shared.utils import ColorProfileAnalyzer

from inky_image_display_sync.api_client import ImageRegisterPayload
from inky_image_display_sync.gemini.config import GeminiConnectionConfig, GeminiSyncConfig
from inky_image_display_sync.immich.config import S3WriterConfig
from inky_image_display_sync.immich.storage import S3StorageClient

if TYPE_CHECKING:
    import logging

    from inky_image_display_sync.gemini.api_client import (
        GeminiDisplayAPIClient,
        GeminiSyncJobItem,
        PromptBlockItem,
        PromptPresetItem,
    )


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
        self.gemini_config = gemini_config or GeminiConnectionConfig()  # ty: ignore[missing-argument]
        self.sync_config = sync_config or GeminiSyncConfig()
        self.storage = S3StorageClient(
            config=s3_config or S3WriterConfig(),  # ty: ignore[missing-argument]
            logger=logger,
        )

    async def sync_all_active_jobs(self) -> list[GeminiSyncResult]:
        """Fetch active Gemini jobs and run each one in sequence."""
        self.storage.ensure_bucket_exists()
        jobs = await self.api_client.get_active_gemini_jobs()
        if not jobs:
            self.logger.info("No active Gemini sync jobs")
            return []

        # Cache blocks so we only fetch them once per run.
        blocks_by_id = {b.id: b for b in await self.api_client.list_prompt_blocks()}

        results: list[GeminiSyncResult] = []
        for job in jobs:
            try:
                preset = await self.api_client.get_prompt_preset(job.prompt_preset_id)
            except Exception as exc:
                self.logger.error("Failed to load preset for job %s: %s", job.name, exc)
                results.append(GeminiSyncResult(job_name=job.name, failed=1, errors=[str(exc)]))
                continue

            result = await self._run_job(job, preset, blocks_by_id)
            results.append(result)
            self.logger.info(
                "Gemini job %s: generated=%d failed=%d",
                job.name,
                result.generated,
                result.failed,
            )
        return results

    async def _run_job(
        self,
        job: GeminiSyncJobItem,
        preset: PromptPresetItem,
        blocks_by_id: dict,
    ) -> GeminiSyncResult:
        result = GeminiSyncResult(job_name=job.name)
        try:
            profile = await self.api_client.get_device_profile(job.target_device_profile_id)
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"target device profile {job.target_device_profile_id} not found: {exc}")
            return result

        is_portrait = job.orientation == "portrait"
        if is_portrait:
            target_width, target_height = profile.height, profile.width
        else:
            target_width, target_height = profile.width, profile.height

        prompt = self._build_prompt(preset, blocks_by_id, is_portrait)
        expires_at = (
            datetime.now() + timedelta(days=job.retention_days)
            if job.retention_days is not None and job.retention_days > 0
            else None
        )

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

    def _build_prompt(
        self,
        preset: PromptPresetItem,
        blocks_by_id: dict[object, PromptBlockItem],
        is_portrait: bool,
    ) -> RenderedPrompt:
        return RenderedPrompt(
            style=blocks_by_id[preset.style_block_id].text,
            palette=blocks_by_id[preset.palette_block_id].text,
            legibility=blocks_by_id[preset.legibility_block_id].text,
            composition=blocks_by_id[preset.composition_block_id].text,
            background=blocks_by_id[preset.background_block_id].text,
            is_portrait=is_portrait,
        )

    async def _generate_one(  # noqa: PLR0913
        self,
        *,
        job: GeminiSyncJobItem,
        subject: str,
        prompt: RenderedPrompt,
        model: str,
        target_width: int,
        target_height: int,
        expires_at: datetime | None,
    ) -> None:
        jpeg_bytes, score = await generate_image_bytes(
            self.gemini_config.api_key,
            prompt,
            subject,
            target_width,
            target_height,
            model=model,
        )
        self.logger.info("Generated %r with %s (Spectra-6 score %.3f)", subject, model, score)

        image_uuid = uuid4()
        storage_path = f"{self.sync_config.storage_prefix}/{image_uuid}.jpg"
        self.storage.upload_from_bytes(
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

    @staticmethod
    def _color_score(image_bytes: bytes) -> float:
        # Exposed for tests; mirrors the score returned by generate_image_bytes.
        return ColorProfileAnalyzer.calculate_compatibility_score(image_bytes)
