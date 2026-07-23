"""Immich sync service - orchestrates fetch, download, store, record workflow."""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from uuid import UUID

from inky_image_display_shared.time import utcnow

from inky_image_display_sync.api_client import ImageTooSmallError, SyncRunReportPayload
from inky_image_display_sync.immich.api_client import (
    ImageItem,
    ImageRegisterPayload,
    ImageUpdatePayload,
    ImmichDisplayAPIClient,
    SyncJobItem,
)
from inky_image_display_sync.immich.client import ImmichClient, SearchFilterCombo
from inky_image_display_sync.immich.config import (
    DeviceRequirements,
    ImmichConnectionConfig,
    ImmichSyncConfig,
    S3WriterConfig,
)
from inky_image_display_sync.immich.models import ImmichAsset
from inky_image_display_sync.immich.storage import S3StorageClient
from inky_image_display_sync.utils.metadata_builder import MetadataBuilder

# Canonical source name marker for Immich records (matches Image.source_name).
IMMICH_SOURCE_NAME = "immich"


class ProcessResult(Enum):
    """Result of processing a single asset."""

    DOWNLOADED = auto()
    SKIPPED_EXISTING = auto()
    SKIPPED_UNDERSIZED = auto()


@dataclass
class SyncResult:
    """Result of a sync operation."""

    fetched: int = 0
    filtered: int = 0  # After client-side filters
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_undersized: int = 0  # Too small for target dimensions
    stopped_at_limit: bool = False  # True if total image limit was reached
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Return human-readable summary."""
        limit_info = ", stopped_at_limit=True" if self.stopped_at_limit else ""
        return (
            f"SyncResult(fetched={self.fetched}, filtered={self.filtered}, "
            f"downloaded={self.downloaded}, skipped_existing={self.skipped_existing}, "
            f"skipped_undersized={self.skipped_undersized}, errors={len(self.errors)}{limit_info})"
        )


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    expired: int = 0
    deleted: int = 0
    protected: int = 0  # Skipped because currently displayed
    storage_errors: int = 0  # Deletion failed

    def __str__(self) -> str:
        """Return human-readable summary."""
        return (
            f"CleanupResult(expired={self.expired}, deleted={self.deleted}, "
            f"protected={self.protected}, storage_errors={self.storage_errors})"
        )


class ImmichSyncService:
    """Orchestrates syncing images from Immich to local storage.

    Workflow:
    1. Load active sync jobs from the Display API
    2. For each job, fetch assets from Immich matching filters
    3. Apply client-side filters (orientation, dimensions, color)
    4. Download original file from Immich
    5. Upload to S3 with path: {prefix}/{asset_id}.{ext}
    6. Register Image record via the Display API
    """

    def __init__(
        self,
        api_client: ImmichDisplayAPIClient,
        logger: logging.Logger,
        connection_config: ImmichConnectionConfig | None = None,
        sync_config: ImmichSyncConfig | None = None,
        s3_config: S3WriterConfig | None = None,
    ) -> None:
        """Initialize sync service.

        Args:
            api_client: Display API HTTP client
            logger: Logger instance
            connection_config: Immich connection settings (defaults to env vars)
            sync_config: Global sync settings (defaults to env vars)
            s3_config: S3 writer config (defaults to env vars)

        """
        self.api_client = api_client
        self.logger = logger

        self.connection_config = connection_config or ImmichConnectionConfig()  # ty: ignore[missing-argument]
        self.sync_config = sync_config or ImmichSyncConfig()
        self.s3_config = s3_config or S3WriterConfig()  # ty: ignore[missing-argument]

        self.immich = ImmichClient(
            config=self.connection_config,
            logger=logger,
        )
        self.storage = S3StorageClient(
            config=self.s3_config,
            logger=logger,
        )

    async def sync_jobs(self, all_active: bool = False) -> None:
        """Execute sync jobs via the Display API, reporting each run.

        The default mode claims due jobs from the API (per-job schedule plus
        Run-now flags), so a single frequent cron drives all cadences. The
        claim advances each job's schedule, and exiting early when nothing
        is due keeps the frequent cron cheap. ``all_active`` ignores the
        schedule and runs every active job (manual/debug invocations).

        Each job's ``max_images`` cap is counted against only the images that
        job uploaded (``images.sync_job_name``), so one job can never spend
        another's budget.
        """
        if all_active:
            jobs = await self.api_client.get_active_sync_jobs()
            if not jobs:
                self.logger.warning("No active sync jobs found")
                return
        else:
            jobs = await self.api_client.claim_due_sync_jobs()
            if not jobs:
                self.logger.debug("No due sync jobs")
                return

        self.logger.info("Found %d sync job(s) to process", len(jobs))

        # Cleanup first so expired images free up each job's budget before
        # counting. Runs only when jobs were handed out, so its cost is
        # bounded by job cadence rather than cron frequency.
        deleted_by_job: dict[str, int] = {}
        if self.sync_config.retention_days > 0:
            _, deleted_by_job = await self._cleanup_expired_images()

        self.storage.ensure_bucket_exists()

        async with self.immich.connect():
            for job in jobs:
                await self._run_and_report_job(job, images_deleted=deleted_by_job.get(job.name, 0))

    async def _run_and_report_job(self, job: SyncJobItem, images_deleted: int) -> None:
        """Run one job and POST its outcome to /api/sync-runs.

        The report is what the UI shows and what clears the job's "Run now"
        flag, so it is sent for every outcome — including the at-cap skip
        (a real answer to "why did nothing new appear?") and hard failures.
        """
        started_at = utcnow()
        result: SyncResult | None = None
        detail: str | None = None
        error: str | None = None

        try:
            max_uploads_remaining: int | None = None
            skip_at_cap = False
            if job.max_images > 0:
                existing = await self._count_job_images(job.name)
                max_uploads_remaining = job.max_images - existing
                self.logger.info(
                    "Job '%s': %d/%d images already synced, can upload %d",
                    job.name,
                    existing,
                    job.max_images,
                    max(0, max_uploads_remaining),
                )
                if max_uploads_remaining <= 0:
                    self.logger.info("Skipping job '%s': reached its image limit (%d)", job.name, job.max_images)
                    detail = f"Nothing to do: job holds {existing}/{job.max_images} images (max_images cap)"
                    skip_at_cap = True

            if not skip_at_cap:
                self.logger.info("Processing sync job: %s", job.name)
                result = await self._sync_job(job, max_uploads_remaining=max_uploads_remaining)
                self.logger.info("Job '%s' completed: %s", job.name, result)
                detail = str(result)
                if result.errors:
                    error = "; ".join(result.errors[:3])
        except Exception as exc:
            self.logger.exception("Job '%s' failed", job.name)
            error = str(exc)

        await self.api_client.report_sync_run(
            SyncRunReportPayload(
                job_type="immich",
                job_id=job.id,
                job_name=job.name,
                status="error" if error else "success",
                started_at=started_at,
                finished_at=utcnow(),
                images_added=result.downloaded if result else 0,
                images_skipped=(result.skipped_existing + result.skipped_undersized) if result else 0,
                images_deleted=images_deleted,
                detail=detail,
                error=error,
            )
        )

    async def _cleanup_expired_images(self) -> tuple[CleanupResult, dict[str, int]]:
        """Remove expired Immich images via the Display API.

        Protects images currently displayed on any device.

        Returns:
            CleanupResult with counts, plus deletions grouped by
            ``sync_job_name`` so each job's run report can show what
            retention removed on its behalf.

        """
        result = CleanupResult()
        deleted_by_job: dict[str, int] = {}
        now = datetime.now()

        expired_images = await self.api_client.list_images(
            source_name=IMMICH_SOURCE_NAME,
            expires_before=now,
        )
        result.expired = len(expired_images)

        if not expired_images:
            self.logger.info("No expired images to clean up")
            return result, deleted_by_job

        devices = await self.api_client.get_devices()
        protected_ids: set[UUID] = {d.current_image_id for d in devices if d.current_image_id is not None}

        self.logger.info(
            "Found %d expired images, %d currently displayed (protected)",
            len(expired_images),
            len(protected_ids),
        )

        for image in expired_images:
            if image.id in protected_ids:
                self.logger.debug("Skipping protected image %s (currently displayed)", image.id)
                result.protected += 1
                continue

            try:
                await self.api_client.delete_image(image.id)
                result.deleted += 1
                if image.sync_job_name:
                    deleted_by_job[image.sync_job_name] = deleted_by_job.get(image.sync_job_name, 0) + 1
            except Exception as e:
                result.storage_errors += 1
                self.logger.warning("Failed to delete image %s: %s", image.id, e)

        self.logger.info("Cleanup completed: %s", result)
        return result, deleted_by_job

    async def _sync_job(self, job: SyncJobItem, max_uploads_remaining: int | None = None) -> SyncResult:
        """Execute a single sync job.

        Args:
            job: Sync job configuration
            max_uploads_remaining: Maximum uploads allowed for this job (None = unlimited)

        Returns:
            SyncResult with counts and any errors

        """
        result = SyncResult()

        device_reqs = await self._get_device_requirements(job.target_device_profile_id, job.orientation)

        fetch_count = job.count * job.overfetch_multiplier

        strategy_desc = f"smart search (query='{job.query}')" if job.strategy == "SMART" else "random"
        self.logger.info(
            "Fetching %d images via %s for job '%s' (overfetch x%d for client-side filters)",
            fetch_count,
            strategy_desc,
            job.name,
            job.overfetch_multiplier,
        )

        try:
            if job.strategy == "SMART":
                assets = await self._fetch_smart_pool(job, fetch_count)
                if job.random_pick and len(assets) > job.count:
                    assets = random.sample(assets, job.count)
                    self.logger.info("Randomly picked %d assets from smart search results", len(assets))
            else:
                assets = await self._fetch_random_pool(job, fetch_count)

            result.fetched = len(assets)
            self.logger.info("Fetched %d assets from Immich", result.fetched)
        except Exception as e:
            result.errors.append(f"Failed to fetch assets: {e}")
            self.logger.exception("Failed to fetch assets from Immich")
            return result

        assets = self._filter_assets(assets, job, device_reqs)
        result.filtered = len(assets)
        if len(assets) < job.count:
            self.logger.warning(
                "Only %d images matched client-side filters (requested %d). "
                "Consider increasing overfetch_multiplier or relaxing filters.",
                len(assets),
                job.count,
            )
        else:
            self.logger.info("Filtered to %d assets matching criteria", len(assets))

        for asset in assets:
            if max_uploads_remaining is not None and result.downloaded >= max_uploads_remaining:
                self.logger.info(
                    "Stopping job '%s': reached total image limit (downloaded %d in this job)",
                    job.name,
                    result.downloaded,
                )
                result.stopped_at_limit = True
                break

            try:
                process_result = await self._process_asset(asset, job, device_reqs)
                if process_result == ProcessResult.DOWNLOADED:
                    result.downloaded += 1
                elif process_result == ProcessResult.SKIPPED_EXISTING:
                    result.skipped_existing += 1
                elif process_result == ProcessResult.SKIPPED_UNDERSIZED:
                    result.skipped_undersized += 1
            except Exception as e:
                error_msg = f"Failed to process asset {asset.id}: {e}"
                result.errors.append(error_msg)
                self.logger.exception("Failed to process asset %s", asset.id)

        return result

    async def _get_device_requirements(self, profile_id: UUID, orientation: str | None) -> DeviceRequirements:
        """Resolve target panel dims from a profile + optional orientation.

        When ``orientation`` is None the job did not specify one, so we
        default to landscape — same shape used for downstream filtering.

        Raises:
            ValueError: If the profile cannot be loaded.

        """
        profile = await self.api_client.get_device_profile(profile_id)
        effective_orientation = orientation or "landscape"

        # profile.width/height are panel-native (landscape). Swap for portrait
        # so width/height describe the orientation-aware raster target.
        if effective_orientation == "portrait":
            width, height = profile.height, profile.width
        else:
            width, height = profile.width, profile.height

        return DeviceRequirements(
            width=width,
            height=height,
            orientation=effective_orientation,
        )

    async def _count_job_images(self, job_name: str) -> int:
        """Count images already synced by a specific job.

        Returns:
            Number of Immich images whose sync_job_name matches ``job_name``

        """
        images = await self.api_client.list_images(source_name=IMMICH_SOURCE_NAME, sync_job_name=job_name)
        return len(images)

    async def _process_asset(
        self,
        asset: ImmichAsset,
        job: SyncJobItem,
        device_reqs: DeviceRequirements,
    ) -> ProcessResult:
        """Process a single asset: download, store, register.

        Args:
            asset: Immich asset to process
            job: Sync job configuration
            device_reqs: Target device display requirements

        Returns:
            ProcessResult indicating what happened

        """
        source_url = self._build_source_url(asset.id)

        existing = None
        if self.sync_config.skip_existing:
            existing = await self._find_existing_image(asset.id)
            if existing:
                self.logger.debug("Skipping existing asset: %s", asset.id)
                return ProcessResult.SKIPPED_EXISTING

        target_width = device_reqs.width
        target_height = device_reqs.height
        storage_path = f"{self.sync_config.storage_prefix}/{asset.id}.jpg"

        if self.storage.object_exists(storage_path):
            self.logger.debug("Object already in S3: %s", storage_path)
        else:
            self.logger.info("Downloading asset: %s", asset.id)
            image_bytes = b"".join([chunk async for chunk in self.immich.download_original(asset.id)])

            self.logger.debug("Processing image via API to %dx%d", target_width, target_height)
            try:
                image_bytes = await self.api_client.process_image(image_bytes, target_width, target_height)
            except ImageTooSmallError:
                self.logger.info("Skipping asset %s: too small for target dimensions", asset.id)
                return ProcessResult.SKIPPED_UNDERSIZED

            self.storage.upload_from_bytes(
                object_path=storage_path,
                data=image_bytes,
                content_type="image/jpeg",
            )

        await self._upsert_image_record(
            asset,
            storage_path,
            source_url,
            job.name,
            device_reqs=device_reqs,
            existing_id=existing.id if existing else None,
        )

        return ProcessResult.DOWNLOADED

    async def _find_existing_image(self, asset_id: str) -> ImageItem | None:
        """Find existing image by (source_name='immich', source_id=asset_id) via the API."""
        return await self.api_client.find_image_by_source(IMMICH_SOURCE_NAME, asset_id)

    async def _upsert_image_record(  # noqa: PLR0913
        self,
        asset: ImmichAsset,
        storage_path: str,
        source_url: str,
        sync_job_name: str,
        device_reqs: DeviceRequirements,
        existing_id: UUID | None = None,
    ) -> None:
        """Create or update Image record via the Display API.

        Recorded ``original_width``/``original_height`` are the raster target
        (orientation-aware: narrow-first for portrait) and ``is_portrait``
        tracks the device orientation. This lets orientation-aware queries
        match using a simple equality on both dims + flag.
        """
        title, description, tags = await self._build_image_metadata(asset)

        expires_at: datetime | None = None
        if self.sync_config.retention_days > 0:
            expires_at = datetime.now() + timedelta(days=self.sync_config.retention_days)

        original_width = device_reqs.width
        original_height = device_reqs.height
        is_portrait = device_reqs.orientation == "portrait"

        if existing_id is not None:
            payload = ImageUpdatePayload(
                title=title,
                description=description,
                tags=tags,
                original_width=original_width,
                original_height=original_height,
                is_portrait=is_portrait,
                expires_at=expires_at,
            )
            await self.api_client.update_image(existing_id, payload)
        else:
            payload = ImageRegisterPayload(
                source_name=IMMICH_SOURCE_NAME,
                source_id=asset.id,
                sync_job_name=sync_job_name,
                storage_path=storage_path,
                source_url=source_url,
                title=title,
                description=description,
                tags=tags,
                original_width=original_width,
                original_height=original_height,
                is_portrait=is_portrait,
                expires_at=expires_at,
            )
            await self.api_client.register_image(payload)

        self.logger.debug("Saved image record for asset: %s", asset.id)

    async def _build_image_metadata(self, asset: ImmichAsset) -> tuple[str | None, str | None, str | None]:
        """Extract natural-language title, description, and tags from an Immich asset."""
        people_names = [p.name for p in (asset.people or []) if p.name]

        city = state = country = None
        date = asset.file_created_at
        if asset.exif_info:
            city = asset.exif_info.city
            state = asset.exif_info.state
            country = asset.exif_info.country
            date = asset.exif_info.date_time_original or date

        album_names = await self._get_asset_album_names(asset.id)

        title = MetadataBuilder.build_title(
            people=people_names if people_names else None,
            city=city,
            country=country,
            date=date,
        )
        description = MetadataBuilder.build_description(
            people=people_names if people_names else None,
            city=city,
            state=state,
            country=country,
            date=date,
            album_names=album_names if album_names else None,
        )
        tags = self._build_tags(city, country, asset.is_favorite, asset.people)
        return title, description, tags

    async def _get_asset_album_names(self, asset_id: str) -> list[str]:
        """Fetch album names for an asset."""
        try:
            albums = await self.immich.get_asset_albums(asset_id)
            return [a.album_name for a in albums]
        except Exception:
            self.logger.debug("Could not fetch albums for asset %s", asset_id)
            return []

    @staticmethod
    def _build_tags(
        city: str | None,
        country: str | None,
        is_favorite: bool,
        people: list | None,
    ) -> str | None:
        """Build comma-separated tags from metadata."""
        tags: list[str] = []
        if city:
            tags.append(city)
        if country:
            tags.append(country)
        if is_favorite:
            tags.append("favorite")
        if people:
            tags.extend(person.name for person in people if person.name)
        return ",".join(tags) if tags else None

    @staticmethod
    def _id_variants(ids: list[str] | None, mode: str) -> list[list[str] | None]:
        """Expand one id filter into the per-query values that realize its mode.

        'all' keeps the whole list in a single query (Immich's native AND);
        'any' yields one single-id list per id so the caller can union the
        per-query results into OR semantics.
        """
        if not ids:
            return [None]
        if mode == "any" and len(ids) > 1:
            return [[single] for single in ids]
        return [ids]

    def _filter_combos(self, job: SyncJobItem, *, tags_any: bool) -> list[SearchFilterCombo]:
        """Cartesian product of per-field query values for a job.

        Fields in 'any' mode contribute one variant per id; 'all' fields
        contribute their full list once. Querying every combination and
        unioning the results yields (any-of-albums) AND (any-of-persons):
        exactly the per-field OR with AND between fields. Tags have no
        stored mode — RANDOM jobs union them (``tags_any``), SMART keeps AND.
        """
        album_variants = self._id_variants(job.album_ids, job.album_match_mode)
        person_variants = self._id_variants(job.person_ids, job.person_match_mode)
        tag_variants = self._id_variants(job.tag_ids, "any" if tags_any else "all")
        return [
            SearchFilterCombo(album_ids=albums, person_ids=persons, tag_ids=tags)
            for albums in album_variants
            for persons in person_variants
            for tags in tag_variants
        ]

    async def _fetch_random_pool(self, job: SyncJobItem, fetch_count: int) -> list[ImmichAsset]:
        """Build a candidate pool for a RANDOM job via Immich's /search/random.

        Immich intersects every multi-value id filter (AND), so union (OR)
        semantics are emulated by issuing one random query per filter
        combination and deduping by asset id: tags always union for RANDOM
        jobs (ANY-tag), albums/persons union when their match mode is 'any'.
        A single combination already samples uniformly in one query.
        """
        combos = self._filter_combos(job, tags_any=True)

        if len(combos) == 1:
            return await self.immich.search_random(job, count_override=fetch_count, combo=combos[0])

        seen: dict[str, ImmichAsset] = {}
        for combo in combos:
            assets = await self.immich.search_random(job, count_override=fetch_count, combo=combo)
            for asset in assets:
                seen.setdefault(asset.id, asset)  # dedupe by stable asset id

        pool = list(seen.values())
        # Each per-combo result is random, but the concatenation groups by
        # combo; shuffle so downstream truncation to job.count draws fairly.
        random.shuffle(pool)
        self.logger.info("Union over %d filter combinations produced %d unique candidates", len(combos), len(pool))
        return pool

    async def _fetch_smart_pool(self, job: SyncJobItem, fetch_count: int) -> list[ImmichAsset]:
        """Build a candidate pool for a SMART job via Immich's /search/smart.

        Same union trick as :meth:`_fetch_random_pool` when album/person match
        mode is 'any', except results are rank-ordered: per-combo results are
        merged round-robin by rank (so truncation keeps each combination's top
        matches), deduped, capped at ``fetch_count``, and enriched once at the
        end — enriching before the cap would fetch details for assets that get
        dropped. Tags keep Immich's native AND for SMART jobs.
        """
        combos = self._filter_combos(job, tags_any=False)

        if len(combos) == 1:
            return await self.immich.search_smart(job, count_override=fetch_count, combo=combos[0])

        per_combo: list[list[ImmichAsset]] = []
        for combo in combos:
            assets = await self.immich.search_smart(
                job, count_override=fetch_count, enrich_with_people=False, combo=combo
            )
            per_combo.append(assets)

        seen: set[str] = set()
        merged: list[ImmichAsset] = []
        for rank in range(max(len(results) for results in per_combo)):
            for results in per_combo:
                if rank < len(results) and results[rank].id not in seen:
                    seen.add(results[rank].id)
                    merged.append(results[rank])

        pool = merged[:fetch_count]
        self.logger.info(
            "Union over %d filter combinations produced %d unique candidates (kept %d)",
            len(combos),
            len(merged),
            len(pool),
        )
        return await self.immich.enrich_assets(pool)

    def _filter_assets(
        self,
        assets: list[ImmichAsset],
        job: SyncJobItem,
        device_reqs: DeviceRequirements,
    ) -> list[ImmichAsset]:
        """Filter assets by orientation and dimensions (client-side).

        Args:
            assets: List of assets from Immich
            job: Sync job configuration
            device_reqs: Target device display requirements

        Returns:
            Filtered list limited to job.count

        """
        filtered: list[ImmichAsset] = []

        for asset in assets:
            width = asset.width
            height = asset.height
            if (not width or not height) and asset.exif_info:
                width = asset.exif_info.exif_image_width
                height = asset.exif_info.exif_image_height
            if not width or not height:
                self.logger.debug("Skipping asset %s: missing dimensions", asset.id)
                continue

            if not self._matches_orientation(width, height, device_reqs.orientation):
                self.logger.debug(
                    "Skipping asset %s: orientation mismatch (%dx%d vs %s)",
                    asset.id,
                    width,
                    height,
                    device_reqs.orientation,
                )
                continue

            if width < device_reqs.width or height < device_reqs.height:
                self.logger.debug(
                    "Skipping asset %s: too small (%dx%d, need %dx%d)",
                    asset.id,
                    width,
                    height,
                    device_reqs.width,
                    device_reqs.height,
                )
                continue

            filtered.append(asset)

            if len(filtered) >= job.count:
                break

        return filtered

    @staticmethod
    def _matches_orientation(width: int, height: int, orientation: str) -> bool:
        """Check if dimensions match the requested orientation."""
        if orientation == "landscape":
            return width > height
        if orientation == "portrait":
            return height > width
        if orientation == "square":
            return width == height
        return True

    def _build_source_url(self, asset_id: str) -> str:
        """Build a user-facing HTTPS URL to the asset on the Immich web UI."""
        base = str(self.connection_config.base_url).rstrip("/")
        return f"{base}/photos/{asset_id}"
