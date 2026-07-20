"""Display-job worker service.

For each claimed display job: generate the structured story (and the AI
illustration where a slot shows the image part), have the API render each
slot part at the panel's native size, upload the screens to S3, and
register them as one image group targeting the job's grid. The grid's
queue takes it from there — the worker never touches a panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from inky_image_display_shared.ai import generate_image_bytes, generate_motd_story
from inky_image_display_shared.time import utcnow

from inky_image_display_sync.api_client import ImageRegisterPayload, SyncRunReportPayload
from inky_image_display_sync.display.api_client import ImageGroupCreatePayload
from inky_image_display_sync.gemini.config import GeminiConnectionConfig
from inky_image_display_sync.gemini.sync_service import build_prompt
from inky_image_display_sync.immich.config import S3WriterConfig
from inky_image_display_sync.immich.storage import S3StorageClient

if TYPE_CHECKING:
    import logging
    from datetime import datetime

    from inky_image_display_shared.ai.gemini_text import MotdStory

    from inky_image_display_sync.display.api_client import (
        DisplayJobAPIClient,
        DisplayJobClaimItem,
        DisplayJobSlotItem,
    )


@dataclass
class DisplayJobResult:
    """Counters returned after running one display job."""

    job_name: str
    screens: int = 0
    errors: list[str] = field(default_factory=list)


class DisplayJobSyncService:
    """Run all claimed display jobs."""

    def __init__(
        self,
        api_client: DisplayJobAPIClient,
        logger: logging.Logger,
        gemini_config: GeminiConnectionConfig | None = None,
        s3_config: S3WriterConfig | None = None,
    ) -> None:
        """Capture dependencies; configs default to environment-driven settings."""
        self.api_client = api_client
        self.logger = logger
        self.gemini_config = gemini_config or GeminiConnectionConfig()  # ty: ignore[missing-argument]
        self.storage = S3StorageClient(
            config=s3_config or S3WriterConfig(),  # ty: ignore[missing-argument]
            logger=logger,
        )

    async def sync_jobs(self) -> list[DisplayJobResult]:
        """Claim due display jobs and run each in sequence, reporting each run."""
        self.storage.ensure_bucket_exists()
        jobs = await self.api_client.claim_due_display_jobs()
        if not jobs:
            self.logger.info("No due display jobs")
            return []

        results: list[DisplayJobResult] = []
        for job in jobs:
            started_at = utcnow()
            result = await self._run_job(job)
            results.append(result)
            self.logger.info("Display job %s: screens=%d errors=%d", job.name, result.screens, len(result.errors))
            await self._report_run(job, result, started_at)
        return results

    async def _report_run(self, job: DisplayJobClaimItem, result: DisplayJobResult, started_at: datetime) -> None:
        """POST the run outcome so the UI can show per-job status."""
        await self.api_client.report_sync_run(
            SyncRunReportPayload(
                job_type="display",
                job_id=job.id,
                job_name=job.name,
                status="error" if result.errors else "success",
                started_at=started_at,
                finished_at=utcnow(),
                images_added=result.screens,
                detail=f"screens={result.screens}",
                error="; ".join(result.errors[:3]) if result.errors else None,
            )
        )

    async def _run_job(self, job: DisplayJobClaimItem) -> DisplayJobResult:
        result = DisplayJobResult(job_name=job.name)
        if not any(slot.parts for slot in job.slots):
            result.errors.append("No grid slots with content parts configured")
            return result
        try:
            story, source_url = await generate_motd_story(
                self.gemini_config.api_key,
                job.content_prompt,
                grounded=job.source_mode == "grounded",
                model=job.text_model_name,
            )
        except Exception as exc:
            self.logger.exception("Story generation failed for job %s", job.name)
            result.errors.append(f"story generation: {exc}")
            return result

        try:
            illustrations = await self._generate_illustrations(job, story)
        except Exception as exc:
            self.logger.exception("Illustration generation failed for job %s", job.name)
            result.errors.append(f"illustration: {exc}")
            illustrations = {}

        group = await self.api_client.create_image_group(
            ImageGroupCreatePayload(
                name=story.headline,
                target_grid_id=job.target_grid_id,
                display_job_id=job.id,
                description=story.what,
                source_url=source_url,
            )
        )
        story_fields: dict[str, str | None] = {
            "headline": story.headline,
            "what": story.what,
            "why": story.why,
            "when_text": story.when_text,
            "takeaway": story.takeaway,
            "source_url": source_url,
            "source_title": story.source_title,
        }
        for slot in job.slots:
            for index, part in enumerate(slot.parts):
                try:
                    screen = await self._render_screen(part, slot, story_fields, illustrations)
                except Exception as exc:
                    self.logger.exception("Rendering %r failed for job %s", part, job.name)
                    result.errors.append(f"{part}: {exc}")
                    continue
                if screen is None:
                    self.logger.info("Part %r not renderable for job %s, skipped", part, job.name)
                    continue
                storage_path = f"groups/{group.id}/{uuid4()}.jpg"
                self.storage.upload_from_bytes(object_path=storage_path, data=screen, content_type="image/jpeg")
                await self.api_client.register_image(
                    ImageRegisterPayload(
                        source_name="display-job",
                        sync_job_name=job.name,
                        storage_path=storage_path,
                        source_url=source_url,
                        title=story.headline,
                        description=f"{part}: generated screen",
                        tags="display-job,generated",
                        original_width=slot.width,
                        original_height=slot.height,
                        is_portrait=slot.is_portrait,
                        group_id=group.id,
                        group_slot_row=slot.row,
                        group_slot_col=slot.col,
                        queue_position=index,
                    )
                )
                result.screens += 1

        if result.screens == 0:
            # A group without screens would sit unplayable in the queue.
            await self.api_client.delete_image_group(group.id)
            result.errors.append("No screens could be rendered")
        return result

    async def _generate_illustrations(self, job: DisplayJobClaimItem, story: MotdStory) -> dict[bool, bytes]:
        """One AI illustration per orientation that actually shows the image part."""
        orientations = {slot.is_portrait for slot in job.slots if "image" in slot.parts}
        if not orientations or job.image_preset_id is None:
            return {}
        preset = await self.api_client.get_prompt_preset(job.image_preset_id)
        blocks_by_id = {b.id: b for b in await self.api_client.list_prompt_blocks()}
        illustrations: dict[bool, bytes] = {}
        for is_portrait in orientations:
            prompt = build_prompt(preset, blocks_by_id, is_portrait)
            self.logger.info("Display job %s: calling Gemini image model=%s", job.name, preset.model_name)
            illustrations[is_portrait] = await generate_image_bytes(
                self.gemini_config.api_key, prompt, story.image_subject, model=preset.model_name
            )
        return illustrations

    async def _render_screen(
        self,
        part: str,
        slot: DisplayJobSlotItem,
        story_fields: dict[str, str | None],
        illustrations: dict[bool, bytes],
    ) -> bytes | None:
        """Render one part at the slot's panel size; None when not renderable."""
        if part == "image":
            raw = illustrations.get(slot.is_portrait) or next(iter(illustrations.values()), None)
            if raw is None:
                return None
            return await self.api_client.process_image(raw, slot.width, slot.height, upscale=True)
        if part == "qr" and not story_fields.get("source_url"):
            return None
        return await self.api_client.render_part(part, slot.width, slot.height, story_fields)
