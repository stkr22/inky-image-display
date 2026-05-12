"""Immich sync service - orchestrates fetch, download, store, record workflow."""

import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from uuid import UUID

from inky_image_display_shared.utils import ColorProfileAnalyzer, ImageProcessor

from inky_image_display_sync.immich.api_client import (
    ImageItem,
    ImageRegisterPayload,
    ImageUpdatePayload,
    ImmichDisplayAPIClient,
    SyncJobItem,
)
from inky_image_display_sync.immich.client import ImmichClient
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
    SKIPPED_COLOR_MISMATCH = auto()
    SKIPPED_LOW_VIBRANCY = auto()


@dataclass
class SyncResult:
    """Result of a sync operation."""

    fetched: int = 0
    filtered: int = 0  # After client-side filters
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_undersized: int = 0  # Too small for target dimensions
    skipped_color_mismatch: int = 0  # Color profile incompatible
    skipped_low_vibrancy: int = 0  # Low saturation and contrast
    stopped_at_limit: bool = False  # True if total image limit was reached
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Return human-readable summary."""
        limit_info = ", stopped_at_limit=True" if self.stopped_at_limit else ""
        return (
            f"SyncResult(fetched={self.fetched}, filtered={self.filtered}, "
            f"downloaded={self.downloaded}, skipped_existing={self.skipped_existing}, "
            f"skipped_undersized={self.skipped_undersized}, "
            f"skipped_color={self.skipped_color_mismatch}, "
            f"skipped_vibrancy={self.skipped_low_vibrancy}, errors={len(self.errors)}{limit_info})"
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

    async def sync_all_active_jobs(self) -> None:
        """Execute all active sync jobs via the Display API."""
        total_uploads = 0

        jobs = await self.api_client.get_active_sync_jobs()

        if not jobs:
            self.logger.warning("No active sync jobs found")
            return

        self.logger.info("Found %d active sync jobs", len(jobs))

        if self.sync_config.retention_days > 0:
            await self._cleanup_expired_images()

        max_images = self.sync_config.max_images
        existing_count = await self._count_existing_immich_images()

        if max_images > 0:
            remaining_capacity = max_images - existing_count
            self.logger.info(
                "Existing Immich images: %d, limit: %d, can upload: %d",
                existing_count,
                max_images,
                max(0, remaining_capacity),
            )
            if remaining_capacity <= 0:
                self.logger.warning(
                    "Total image limit reached (%d/%d), skipping all jobs",
                    existing_count,
                    max_images,
                )
                return

        self.storage.ensure_bucket_exists()

        async with self.immich.connect():
            for job in jobs:
                if max_images > 0:
                    remaining = max_images - existing_count - total_uploads
                    if remaining <= 0:
                        self.logger.info(
                            "Skipping job '%s': total image limit (%d) already reached",
                            job.name,
                            max_images,
                        )
                        continue

                self.logger.info("Processing sync job: %s", job.name)
                try:
                    max_uploads_remaining = max_images - existing_count - total_uploads if max_images > 0 else None
                    result = await self._sync_job(job, max_uploads_remaining=max_uploads_remaining)
                    total_uploads += result.downloaded
                    self.logger.info("Job '%s' completed: %s", job.name, result)
                except Exception:
                    self.logger.exception("Job '%s' failed", job.name)

        if max_images > 0:
            self.logger.info(
                "Uploaded %d images this run, total Immich images now: %d/%d",
                total_uploads,
                existing_count + total_uploads,
                max_images,
            )

    async def _cleanup_expired_images(self) -> CleanupResult:
        """Remove expired Immich images via the Display API.

        Protects images currently displayed on any device.

        Returns:
            CleanupResult with counts and any errors

        """
        result = CleanupResult()
        now = datetime.now()

        expired_images = await self.api_client.list_images(
            source_name=IMMICH_SOURCE_NAME,
            expires_before=now,
        )
        result.expired = len(expired_images)

        if not expired_images:
            self.logger.info("No expired images to clean up")
            return result

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
            except Exception as e:
                result.storage_errors += 1
                self.logger.warning("Failed to delete image %s: %s", image.id, e)

        self.logger.info("Cleanup completed: %s", result)
        return result

    async def _sync_job(self, job: SyncJobItem, max_uploads_remaining: int | None = None) -> SyncResult:
        """Execute a single sync job.

        Args:
            job: Sync job configuration
            max_uploads_remaining: Maximum uploads allowed for this job (None = unlimited)

        Returns:
            SyncResult with counts and any errors

        """
        result = SyncResult()

        device_reqs = await self._get_device_requirements(job.target_device_id)

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
                assets = await self.immich.search_smart(job, count_override=fetch_count)
                if job.random_pick and len(assets) > job.count:
                    assets = random.sample(assets, job.count)
                    self.logger.info("Randomly picked %d assets from smart search results", len(assets))
            else:
                assets = await self.immich.search_random(job, count_override=fetch_count)

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
                self._update_result_counters(result, process_result)
            except Exception as e:
                error_msg = f"Failed to process asset {asset.id}: {e}"
                result.errors.append(error_msg)
                self.logger.exception("Failed to process asset %s", asset.id)

        return result

    @staticmethod
    def _update_result_counters(result: SyncResult, process_result: ProcessResult) -> None:
        """Update result counters based on process result."""
        if process_result == ProcessResult.DOWNLOADED:
            result.downloaded += 1
        elif process_result == ProcessResult.SKIPPED_EXISTING:
            result.skipped_existing += 1
        elif process_result == ProcessResult.SKIPPED_UNDERSIZED:
            result.skipped_undersized += 1
        elif process_result == ProcessResult.SKIPPED_COLOR_MISMATCH:
            result.skipped_color_mismatch += 1
        elif process_result == ProcessResult.SKIPPED_LOW_VIBRANCY:
            result.skipped_low_vibrancy += 1

    async def _get_device_requirements(self, device_id: UUID) -> DeviceRequirements:
        """Get display requirements from the Display API.

        Args:
            device_id: UUID of target device

        Returns:
            DeviceRequirements with width, height, and orientation

        Raises:
            ValueError: If device not found

        """
        devices = await self.api_client.get_devices(id=device_id)
        if not devices:
            raise ValueError(f"Target device not found: {device_id}")

        device = devices[0]
        orientation = device.display_orientation

        # device.display_width/height are the panel's native (always landscape)
        # dims. Swap for portrait so width/height describe the orientation-aware
        # raster target and are what gets recorded against the Image row.
        if orientation == "portrait":
            width, height = device.display_height, device.display_width
        else:
            width, height = device.display_width, device.display_height

        return DeviceRequirements(
            width=width,
            height=height,
            orientation=orientation,
            display_model=device.display_model,
        )

    async def _count_existing_immich_images(self) -> int:
        """Count images already synced from Immich.

        Returns:
            Number of images with source_name == 'immich'

        """
        images = await self.api_client.list_images(source_name=IMMICH_SOURCE_NAME)
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
            image_bytes = await self._collect_stream(self.immich.download_original(asset.id))

            min_score = job.min_color_score
            if min_score > 0:
                score = ColorProfileAnalyzer.calculate_compatibility_score(image_bytes)
                if score < min_score:
                    self.logger.info("Skipping asset %s: color score %.2f < %.2f", asset.id, score, min_score)
                    return ProcessResult.SKIPPED_COLOR_MISMATCH
                self.logger.debug("Asset %s color score: %.2f", asset.id, score)

            min_vibrancy = job.min_vibrancy_score
            if min_vibrancy > 0:
                vibrancy = ColorProfileAnalyzer.calculate_vibrancy_score(image_bytes)
                if vibrancy < min_vibrancy:
                    self.logger.info("Skipping asset %s: vibrancy score %.2f < %.2f", asset.id, vibrancy, min_vibrancy)
                    return ProcessResult.SKIPPED_LOW_VIBRANCY
                self.logger.debug("Asset %s vibrancy score: %.2f", asset.id, vibrancy)

            self.logger.debug("Processing image to %dx%d", target_width, target_height)
            processed = ImageProcessor.process_for_display(
                image_bytes,
                target_width,
                target_height,
            )
            if processed is None:
                self.logger.info("Skipping asset %s: too small for target dimensions", asset.id)
                return ProcessResult.SKIPPED_UNDERSIZED
            image_bytes = processed

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

    @staticmethod
    async def _collect_stream(stream: AsyncIterator[bytes]) -> bytes:
        """Collect async byte stream into a single bytes object."""
        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        return b"".join(chunks)

    def _build_source_url(self, asset_id: str) -> str:
        """Build a user-facing HTTPS URL to the asset on the Immich web UI."""
        base = str(self.connection_config.base_url).rstrip("/")
        return f"{base}/photos/{asset_id}"
