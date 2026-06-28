from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_sync.api_client import DeviceItem, DeviceProfileItem, ImageItem, ImageTooSmallError
from inky_image_display_sync.immich.api_client import ImmichDisplayAPIClient, SyncJobItem
from inky_image_display_sync.immich.config import DeviceRequirements, ImmichSyncConfig, S3WriterConfig
from inky_image_display_sync.immich.models import ImmichAsset, ImmichExifInfo
from inky_image_display_sync.immich.sync_service import (
    CleanupResult,
    ImmichSyncService,
    ProcessResult,
)
from pydantic import ValidationError


class TestRetentionDaysConfig:
    def test_default_is_seven_and_negative_rejected(self) -> None:
        config = ImmichSyncConfig(
            _env_file=None,  # ty: ignore[unknown-argument]
        )
        assert config.retention_days == 7
        with pytest.raises(ValidationError):
            ImmichSyncConfig(
                _env_file=None,  # ty: ignore[unknown-argument]
                retention_days=-1,
            )


def _make_service(
    api_client: ImmichDisplayAPIClient | MagicMock | None = None,
    retention_days: int = 7,
) -> ImmichSyncService:
    """Create an ImmichSyncService with mocked dependencies."""
    if api_client is None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
    logger = MagicMock()
    sync_config = ImmichSyncConfig(
        _env_file=None,  # ty: ignore[unknown-argument]
        retention_days=retention_days,
    )
    s3_config = S3WriterConfig(
        endpoint="localhost:9000",
        bucket="test-bucket",
        secure=False,
        access_key="test-key",
        secret_key="test-secret",
    )
    with patch("inky_image_display_sync.immich.sync_service.ImmichClient"):
        service = ImmichSyncService(
            api_client=api_client,
            logger=logger,
            connection_config=MagicMock(),
            sync_config=sync_config,
            s3_config=s3_config,
        )
    service.storage = MagicMock()
    return service


def _make_image_item(
    source_name: str = "immich",
    source_id: str | None = "test-asset",
    source_url: str | None = "https://immich.example.com/photos/test-asset",
    storage_path: str = "immich/test-asset.jpg",
    expires_at: datetime | None = None,
) -> ImageItem:
    return ImageItem(
        id=uuid4(),
        source_name=source_name,
        source_id=source_id,
        source_url=source_url,
        storage_path=storage_path,
        expires_at=expires_at,
    )


def _make_device_item(
    current_image_id=None,
) -> DeviceItem:
    return DeviceItem(
        id=uuid4(),
        device_id="test-display",
        device_profile_id=uuid4(),
        display_orientation="landscape",
        current_image_id=current_image_id,
    )


class TestCleanupExpiredImages:
    @pytest.mark.asyncio
    async def test_no_expired_images_returns_empty_result(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        api_client.list_images.return_value = []
        service = _make_service(api_client=api_client)

        result = await service._cleanup_expired_images()

        assert result.expired == 0
        assert result.deleted == 0

    @pytest.mark.asyncio
    async def test_expired_images_deleted_via_api(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        expired_image = _make_image_item(expires_at=datetime.now() - timedelta(days=1))
        api_client.list_images.return_value = [expired_image]
        api_client.get_devices.return_value = []
        service = _make_service(api_client=api_client)

        result = await service._cleanup_expired_images()

        assert result.expired == 1
        assert result.deleted == 1
        assert result.protected == 0
        api_client.delete_image.assert_called_once_with(expired_image.id)

    @pytest.mark.asyncio
    async def test_currently_displayed_images_protected(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        expired_image = _make_image_item(expires_at=datetime.now() - timedelta(days=1))
        api_client.list_images.return_value = [expired_image]
        # The expired image's ID is in use by a device
        api_client.get_devices.return_value = [_make_device_item(current_image_id=expired_image.id)]
        service = _make_service(api_client=api_client)

        result = await service._cleanup_expired_images()

        assert result.expired == 1
        assert result.deleted == 0
        assert result.protected == 1
        api_client.delete_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_failure_counts_storage_error(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        expired_image = _make_image_item(expires_at=datetime.now() - timedelta(days=1))
        api_client.list_images.return_value = [expired_image]
        api_client.get_devices.return_value = []
        api_client.delete_image.side_effect = Exception("API connection failed")
        service = _make_service(api_client=api_client)

        result = await service._cleanup_expired_images()

        assert result.deleted == 0
        assert result.storage_errors == 1

    @pytest.mark.asyncio
    async def test_non_immich_images_excluded_by_source_name_filter(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        # list_images with source_name returns empty (non-Immich excluded)
        api_client.list_images.return_value = []
        service = _make_service(api_client=api_client)

        result = await service._cleanup_expired_images()

        assert result.expired == 0
        api_client.list_images.assert_called_once()
        call_kwargs = api_client.list_images.call_args
        assert call_kwargs.kwargs.get("source_name") == "immich"


class TestCleanupInSyncFlow:
    @pytest.mark.asyncio
    async def test_cleanup_skipped_when_retention_days_zero(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        api_client.get_active_sync_jobs.return_value = []
        service = _make_service(api_client=api_client, retention_days=0)

        with patch.object(service, "_cleanup_expired_images", new_callable=AsyncMock) as mock_cleanup:
            await service.sync_all_active_jobs()

        mock_cleanup.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_runs_when_retention_days_positive(self) -> None:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        # Return one job so cleanup is triggered, then return empty image list
        job = MagicMock(spec=SyncJobItem)
        job.name = "test-job"
        job.max_images = 10
        api_client.get_active_sync_jobs.return_value = [job]
        api_client.list_images.return_value = []
        service = _make_service(api_client=api_client, retention_days=7)

        with patch.object(service, "_cleanup_expired_images", new_callable=AsyncMock) as mock_cleanup:
            mock_cleanup.return_value = CleanupResult()
            with patch.object(service, "_count_job_images", new_callable=AsyncMock, return_value=10):
                await service.sync_all_active_jobs()

        mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_called_before_capacity_check() -> None:
    """Verify cleanup runs before a job's per-job capacity check."""
    api_client = AsyncMock(spec=ImmichDisplayAPIClient)
    job = MagicMock(spec=SyncJobItem)
    job.name = "test-job"
    job.max_images = 5
    api_client.get_active_sync_jobs.return_value = [job]

    call_order: list[str] = []

    async def mock_cleanup() -> CleanupResult:
        call_order.append("cleanup")
        return CleanupResult(expired=3, deleted=3)

    async def mock_count(_job_name: str) -> int:
        call_order.append("count")
        return 5  # At limit

    service = _make_service(api_client=api_client, retention_days=7)

    with (
        patch.object(service, "_cleanup_expired_images", side_effect=mock_cleanup),
        patch.object(service, "_count_job_images", side_effect=mock_count),
    ):
        await service.sync_all_active_jobs()

    assert call_order[0] == "cleanup"
    assert "count" in call_order


def _make_profile_item(width: int = 1600, height: int = 1200):
    return DeviceProfileItem(
        id=uuid4(),
        key="inky_impression_13_spectra6",
        name="Test profile",
        width=width,
        height=height,
        model="test-model",
        is_default=True,
    )


class TestGetDeviceRequirementsPortrait:
    """Test that _get_device_requirements swaps dimensions for portrait orientation."""

    def _service(self) -> ImmichSyncService:
        api_client = AsyncMock(spec=ImmichDisplayAPIClient)
        api_client.get_device_profile.return_value = _make_profile_item()
        service = ImmichSyncService.__new__(ImmichSyncService)
        service.api_client = api_client
        service.logger = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_landscape_and_none_preserve_dimensions(self) -> None:
        service = self._service()

        reqs = await service._get_device_requirements(uuid4(), "landscape")
        assert (reqs.width, reqs.height, reqs.orientation) == (1600, 1200, "landscape")

        # Missing orientation defaults to landscape.
        reqs = await service._get_device_requirements(uuid4(), None)
        assert (reqs.width, reqs.height, reqs.orientation) == (1600, 1200, "landscape")

    @pytest.mark.asyncio
    async def test_portrait_swaps_dimensions(self) -> None:
        service = self._service()

        reqs = await service._get_device_requirements(uuid4(), "portrait")

        assert reqs.width == 1200
        assert reqs.height == 1600
        assert reqs.orientation == "portrait"


class TestFilterAssets:
    """Test _filter_assets uses top-level dimensions with EXIF fallback."""

    def _make_service(self) -> ImmichSyncService:
        with patch("inky_image_display_sync.immich.sync_service.ImmichClient"):
            service = ImmichSyncService(
                api_client=AsyncMock(spec=ImmichDisplayAPIClient),
                logger=MagicMock(),
                connection_config=MagicMock(),
                sync_config=ImmichSyncConfig(),
                s3_config=S3WriterConfig(
                    endpoint="localhost:9000",
                    bucket="test",
                    secure=False,
                    access_key="k",
                    secret_key="s",
                ),
            )
        service.storage = MagicMock()
        return service

    def _make_asset(
        self,
        asset_id: str = "a1",
        width: int | None = None,
        height: int | None = None,
        exif_width: int | None = None,
        exif_height: int | None = None,
    ) -> ImmichAsset:
        exif = None
        if exif_width is not None or exif_height is not None:
            exif = ImmichExifInfo(exifImageWidth=exif_width, exifImageHeight=exif_height)
        return ImmichAsset(
            id=asset_id,
            type="IMAGE",
            originalFileName="test.jpg",
            originalMimeType="image/jpeg",
            checksum="abc",
            fileCreatedAt=datetime.now(),
            width=width,
            height=height,
            exifInfo=exif,
        )

    def _make_job(self, count: int = 10) -> SyncJobItem:
        return SyncJobItem(
            id=uuid4(),
            name="test-job",
            is_active=True,
            target_device_profile_id=uuid4(),
            orientation=None,
            strategy="RANDOM",
            query=None,
            count=count,
            max_images=10,
            random_pick=False,
            overfetch_multiplier=3,
            album_ids=None,
            person_ids=None,
            tag_ids=None,
            is_favorite=None,
            city=None,
            state=None,
            country=None,
            taken_after=None,
            taken_before=None,
            rating=None,
        )

    def _landscape_reqs(self) -> DeviceRequirements:
        return DeviceRequirements(width=1920, height=1080, orientation="landscape")

    def _portrait_reqs(self) -> DeviceRequirements:
        return DeviceRequirements(width=1080, height=1920, orientation="portrait")

    def test_top_level_dimensions_select_matching_orientation(self) -> None:
        service = self._make_service()
        assets = [
            self._make_asset("landscape", width=4000, height=3000),
            self._make_asset("portrait", width=3000, height=4000),
        ]
        landscape = service._filter_assets(assets, self._make_job(), self._landscape_reqs())
        assert [a.id for a in landscape] == ["landscape"]

        portrait = service._filter_assets(assets, self._make_job(), self._portrait_reqs())
        assert [a.id for a in portrait] == ["portrait"]

    def test_exif_fallback_when_no_top_level_dims(self) -> None:
        service = self._make_service()
        assets = [
            self._make_asset("exif-landscape", exif_width=4000, exif_height=3000),
        ]
        result = service._filter_assets(assets, self._make_job(), self._landscape_reqs())
        assert len(result) == 1
        assert result[0].id == "exif-landscape"

    def test_skips_asset_without_any_dimensions(self) -> None:
        service = self._make_service()
        assets = [self._make_asset("no-dims")]
        result = service._filter_assets(assets, self._make_job(), self._landscape_reqs())
        assert len(result) == 0

    def test_skips_undersized_assets(self) -> None:
        service = self._make_service()
        assets = [
            self._make_asset("too-small", width=800, height=600),
        ]
        result = service._filter_assets(assets, self._make_job(), self._landscape_reqs())
        assert len(result) == 0

    def test_limits_to_job_count(self) -> None:
        service = self._make_service()
        assets = [self._make_asset(f"a{i}", width=4000, height=3000) for i in range(20)]
        result = service._filter_assets(assets, self._make_job(count=5), self._landscape_reqs())
        assert len(result) == 5

    def test_top_level_preferred_over_exif(self) -> None:
        service = self._make_service()
        assets = [
            self._make_asset("mixed", width=4000, height=3000, exif_width=3000, exif_height=4000),
        ]
        result = service._filter_assets(assets, self._make_job(), self._landscape_reqs())
        assert len(result) == 1


class TestProcessAssetCallsApiForResize:
    """``_process_asset`` should forward bytes to the API for resize/crop and
    map an ``ImageTooSmallError`` to ``SKIPPED_UNDERSIZED``.
    """

    def _make_service(self) -> ImmichSyncService:
        with patch("inky_image_display_sync.immich.sync_service.ImmichClient"):
            service = ImmichSyncService(
                api_client=AsyncMock(spec=ImmichDisplayAPIClient),
                logger=MagicMock(),
                connection_config=MagicMock(),
                sync_config=ImmichSyncConfig(),
                s3_config=S3WriterConfig(
                    endpoint="localhost:9000",
                    bucket="test",
                    secure=False,
                    access_key="k",
                    secret_key="s",
                ),
            )
        service.storage = MagicMock()
        service.storage.object_exists.return_value = False
        return service

    def _make_asset(self) -> ImmichAsset:
        return ImmichAsset(
            id="test-asset",
            type="IMAGE",
            originalFileName="test.jpg",
            originalMimeType="image/jpeg",
            checksum="abc",
            fileCreatedAt=datetime.now(),
            width=4000,
            height=3000,
        )

    def _make_job(self) -> SyncJobItem:
        return SyncJobItem(
            id=uuid4(),
            name="test-job",
            is_active=True,
            target_device_profile_id=uuid4(),
            orientation=None,
            strategy="RANDOM",
            query=None,
            count=10,
            max_images=10,
            random_pick=False,
            overfetch_multiplier=3,
            album_ids=None,
            person_ids=None,
            tag_ids=None,
            is_favorite=None,
            city=None,
            state=None,
            country=None,
            taken_after=None,
            taken_before=None,
            rating=None,
        )

    def _landscape_reqs(self) -> DeviceRequirements:
        return DeviceRequirements(width=1920, height=1080, orientation="landscape")

    @pytest.mark.asyncio
    async def test_processes_via_api_and_uploads(self) -> None:
        service = self._make_service()
        service.immich = MagicMock()

        async def fake_stream() -> AsyncIterator[bytes]:
            yield b"raw-image-data"

        service.immich.download_original = MagicMock(return_value=fake_stream())
        process_mock = AsyncMock(return_value=b"processed-image")

        with (
            patch.object(service.api_client, "process_image", process_mock),
            patch.object(service, "_find_existing_image", new_callable=AsyncMock, return_value=None),
            patch.object(service, "_upsert_image_record", new_callable=AsyncMock),
        ):
            result = await service._process_asset(self._make_asset(), self._make_job(), self._landscape_reqs())

        assert result == ProcessResult.DOWNLOADED
        process_mock.assert_awaited_once()
        # Payload uploaded to S3 must be the API's processed bytes, not the raw download.
        upload_kwargs = service.storage.upload_from_bytes.call_args.kwargs  # ty: ignore[unresolved-attribute]
        assert upload_kwargs["data"] == b"processed-image"

    @pytest.mark.asyncio
    async def test_too_small_maps_to_skipped_undersized(self) -> None:
        service = self._make_service()
        service.immich = MagicMock()

        async def fake_stream() -> AsyncIterator[bytes]:
            yield b"raw-image-data"

        service.immich.download_original = MagicMock(return_value=fake_stream())
        process_mock = AsyncMock(side_effect=ImageTooSmallError("too small"))

        with (
            patch.object(service.api_client, "process_image", process_mock),
            patch.object(service, "_find_existing_image", new_callable=AsyncMock, return_value=None),
            patch.object(service, "_upsert_image_record", new_callable=AsyncMock),
        ):
            result = await service._process_asset(self._make_asset(), self._make_job(), self._landscape_reqs())

        assert result == ProcessResult.SKIPPED_UNDERSIZED
        service.storage.upload_from_bytes.assert_not_called()  # ty: ignore[unresolved-attribute]


def _make_random_job(
    count: int = 10,
    overfetch_multiplier: int = 3,
    tag_ids: list[str] | None = None,
    strategy: str = "RANDOM",
    query: str | None = None,
) -> SyncJobItem:
    return SyncJobItem(
        id=uuid4(),
        name="test-job",
        is_active=True,
        target_device_profile_id=uuid4(),
        orientation=None,
        strategy=strategy,
        query=query,
        count=count,
        max_images=10,
        random_pick=False,
        overfetch_multiplier=overfetch_multiplier,
        album_ids=None,
        person_ids=None,
        tag_ids=tag_ids,
        is_favorite=None,
        city=None,
        state=None,
        country=None,
        taken_after=None,
        taken_before=None,
        rating=None,
    )


def _make_landscape_asset(asset_id: str) -> ImmichAsset:
    return ImmichAsset(
        id=asset_id,
        type="IMAGE",
        originalFileName="test.jpg",
        originalMimeType="image/jpeg",
        checksum="abc",
        fileCreatedAt=datetime.now(),
        width=4000,
        height=3000,
    )


class TestFetchRandomPool:
    """``_fetch_random_pool`` builds the candidate pool with ANY-tag union."""

    @pytest.mark.asyncio
    async def test_no_tags_single_query(self) -> None:
        service = _make_service()
        service.immich = AsyncMock()
        assets = [_make_landscape_asset("a1")]
        service.immich.search_random.return_value = assets

        result = await service._fetch_random_pool(_make_random_job(tag_ids=None), fetch_count=30)

        assert result == assets
        service.immich.search_random.assert_awaited_once()
        assert "tag_id_override" not in service.immich.search_random.call_args.kwargs

    @pytest.mark.asyncio
    async def test_single_tag_single_query(self) -> None:
        service = _make_service()
        service.immich = AsyncMock()
        service.immich.search_random.return_value = [_make_landscape_asset("a1")]

        await service._fetch_random_pool(_make_random_job(tag_ids=["t1"]), fetch_count=30)

        service.immich.search_random.assert_awaited_once()
        assert "tag_id_override" not in service.immich.search_random.call_args.kwargs

    @pytest.mark.asyncio
    async def test_multi_tag_union_dedupes(self) -> None:
        service = _make_service()
        service.immich = AsyncMock()
        a1, a2, a3 = (_make_landscape_asset("a1"), _make_landscape_asset("a2"), _make_landscape_asset("a3"))
        # a2 appears under both tags and must be deduped.
        service.immich.search_random.side_effect = [[a1, a2], [a2, a3]]

        result = await service._fetch_random_pool(_make_random_job(tag_ids=["t1", "t2"]), fetch_count=30)

        # Set membership — order is shuffled, so never assert list order.
        assert {a.id for a in result} == {"a1", "a2", "a3"}
        assert service.immich.search_random.await_count == 2
        overrides = {c.kwargs["tag_id_override"] for c in service.immich.search_random.call_args_list}
        assert overrides == {"t1", "t2"}

    @pytest.mark.asyncio
    async def test_multi_tag_shuffled_single_tag_not(self) -> None:
        service = _make_service()
        service.immich = AsyncMock()
        service.immich.search_random.return_value = [_make_landscape_asset("a1")]

        with patch("inky_image_display_sync.immich.sync_service.random.shuffle") as shuffle_mock:
            await service._fetch_random_pool(_make_random_job(tag_ids=["t1"]), fetch_count=30)
            shuffle_mock.assert_not_called()  # single tag: results already random

            service.immich.search_random.side_effect = [[_make_landscape_asset("a1")], [_make_landscape_asset("a2")]]
            await service._fetch_random_pool(_make_random_job(tag_ids=["t1", "t2"]), fetch_count=30)
            shuffle_mock.assert_called_once()  # multi-tag union mixed before truncation


class TestSyncJobRandomFlow:
    """RANDOM jobs fetch a pool then filter down to job.count (no extra sampling)."""

    def _reqs(self) -> DeviceRequirements:
        return DeviceRequirements(width=1920, height=1080, orientation="landscape")

    @pytest.mark.asyncio
    async def test_multi_tag_job_filters_to_count(self) -> None:
        service = _make_service()
        pool = [_make_landscape_asset(f"a{i}") for i in range(20)]

        with (
            patch.object(service, "_get_device_requirements", new_callable=AsyncMock, return_value=self._reqs()),
            patch.object(service, "_fetch_random_pool", new_callable=AsyncMock, return_value=pool),
            patch.object(
                service, "_process_asset", new_callable=AsyncMock, return_value=ProcessResult.DOWNLOADED
            ) as process_mock,
        ):
            result = await service._sync_job(_make_random_job(count=5, tag_ids=["t1", "t2"]))

        assert result.filtered == 5
        assert process_mock.await_count == 5

    @pytest.mark.asyncio
    async def test_pool_smaller_than_count(self) -> None:
        service = _make_service()
        pool = [_make_landscape_asset(f"a{i}") for i in range(3)]

        with (
            patch.object(service, "_get_device_requirements", new_callable=AsyncMock, return_value=self._reqs()),
            patch.object(service, "_fetch_random_pool", new_callable=AsyncMock, return_value=pool),
            patch.object(
                service, "_process_asset", new_callable=AsyncMock, return_value=ProcessResult.DOWNLOADED
            ) as process_mock,
        ):
            result = await service._sync_job(_make_random_job(count=5))

        assert result.filtered == 3
        assert process_mock.await_count == 3

    @pytest.mark.asyncio
    async def test_smart_path_does_not_call_fetch_random_pool(self) -> None:
        service = _make_service()
        service.immich = AsyncMock()
        service.immich.search_smart.return_value = [_make_landscape_asset(f"a{i}") for i in range(5)]

        with (
            patch.object(service, "_get_device_requirements", new_callable=AsyncMock, return_value=self._reqs()),
            patch.object(service, "_fetch_random_pool", new_callable=AsyncMock) as fetch_pool_mock,
            patch.object(service, "_process_asset", new_callable=AsyncMock, return_value=ProcessResult.DOWNLOADED),
        ):
            await service._sync_job(_make_random_job(count=10, strategy="SMART", query="beach"))

        fetch_pool_mock.assert_not_called()
        service.immich.search_smart.assert_awaited_once()
