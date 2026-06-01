"""Async HTTP client for Immich API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Any, Protocol, runtime_checkable

import httpx

from inky_image_display_sync.immich.config import ImmichConnectionConfig
from inky_image_display_sync.immich.models import (
    AlbumsResponse,
    ImmichAlbum,
    ImmichAsset,
    RandomSearchResponse,
    SmartSearchResponse,
)
from inky_image_display_sync.immich.payloads import (
    RandomSearchPayload,
    SmartSearchPayload,
)

# Immich's /search/random endpoint caps `size` at 1000.
RANDOM_SEARCH_MAX_SIZE = 1000


@runtime_checkable
class ImmichJobFilter(Protocol):
    """Structural protocol for objects that carry Immich search parameters.

    Both ``ImmichSyncJob`` (ORM) and ``SyncJobItem`` (API client model) satisfy
    this protocol, allowing ``ImmichClient`` to accept either without importing
    the ORM model directly.
    """

    count: int
    query: str | None
    album_ids: list[str] | None
    person_ids: list[str] | None
    tag_ids: list[str] | None
    is_favorite: bool | None
    city: str | None
    state: str | None
    country: str | None
    taken_after: datetime | None
    taken_before: datetime | None
    rating: int | None


class ImmichClientError(Exception):
    """Base exception for Immich client errors."""


class ImmichAuthError(ImmichClientError):
    """Authentication failed."""


class ImmichNotFoundError(ImmichClientError):
    """Resource not found."""


class ImmichClient:
    """Async client for Immich REST API.

    Handles authentication, request/response serialization, and error handling.
    Uses httpx for async HTTP with connection pooling.
    """

    def __init__(
        self,
        config: ImmichConnectionConfig,
        logger: logging.Logger,
    ) -> None:
        """Initialize the Immich client.

        Args:
            config: Connection configuration (includes api_key)
            logger: Logger instance

        """
        self.base_url = str(config.base_url).rstrip("/")
        self.timeout = config.timeout_seconds
        self.verify_ssl = config.verify_ssl
        self.api_key = config.api_key
        self.logger = logger
        self._client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def connect(self) -> AsyncIterator["ImmichClient"]:
        """Context manager for HTTP client lifecycle."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
            timeout=httpx.Timeout(self.timeout),
            verify=self.verify_ssl,
        )
        try:
            yield self
        finally:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated request to Immich API."""
        if self._client is None:
            raise RuntimeError("Client not connected. Use async with client.connect():")

        response = await self._client.request(method, path, **kwargs)

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise ImmichAuthError("Invalid API key")
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise ImmichNotFoundError(f"Resource not found: {path}")

        response.raise_for_status()
        return response

    async def search_random(
        self,
        job: ImmichJobFilter,
        count_override: int | None = None,
        *,
        tag_id_override: str | None = None,
    ) -> list[ImmichAsset]:
        """Fetch random assets matching job criteria.

        Immich's /search/random orders the whole filtered set randomly, so a
        single call yields a uniform random sample across the entire album.

        Args:
            job: Sync job with filter configuration.
            count_override: Override job.count (for overfetching with client-side filters).
            tag_id_override: When set, the payload carries exactly this single
                tag id instead of ``job.tag_ids`` — used by callers to build
                ANY-tag (union) semantics across multiple per-tag queries.

        Returns:
            List of matching assets in random order.

        """
        payload = self._build_random_payload(job, count_override, tag_id_override=tag_id_override)
        body = payload.model_dump(by_alias=True, exclude_none=True)
        self.logger.debug("Searching random assets with filters: %s", body)

        response = await self._request("POST", "/api/search/random", json=body)
        return RandomSearchResponse.model_validate(response.json()).root

    async def search_smart(
        self,
        job: ImmichJobFilter,
        count_override: int | None = None,
        enrich_with_people: bool = True,
    ) -> list[ImmichAsset]:
        """Fetch assets matching semantic query with filters (CLIP-based).

        Note: Smart search doesn't support withPeople parameter. If enrich_with_people
        is True, we fetch full asset details for each result to include people data.

        Args:
            job: Sync job with filter configuration (must have query set)
            count_override: Override job.count (for overfetching with client-side filters)
            enrich_with_people: Fetch full details to include people data

        Returns:
            List of matching assets ranked by semantic similarity

        Raises:
            ValueError: If job.query is not set

        """
        if not job.query:
            raise ValueError("Smart search requires a query string")

        payload = self._build_smart_payload(job, count_override)
        body = payload.model_dump(by_alias=True, exclude_none=True)
        self.logger.debug("Searching smart assets with query '%s' and filters: %s", job.query, body)

        response = await self._request("POST", "/api/search/smart", json=body)
        result = SmartSearchResponse.model_validate(response.json())
        assets = result.assets.items

        # Smart search doesn't include people data - fetch full details if needed
        if enrich_with_people and assets:
            self.logger.debug("Enriching %d assets with full details (people data)", len(assets))
            enriched = []
            for asset in assets:
                try:
                    full_asset = await self.get_asset(asset.id)
                    enriched.append(full_asset)
                except Exception:
                    self.logger.warning("Failed to enrich asset %s, using partial data", asset.id)
                    enriched.append(asset)
            return enriched

        return assets

    def _build_random_payload(
        self,
        job: ImmichJobFilter,
        count_override: int | None = None,
        *,
        tag_id_override: str | None = None,
    ) -> RandomSearchPayload:
        """Build payload for random search from job config.

        ``size`` is clamped to Immich's maximum (1000); a high count *
        overfetch_multiplier would otherwise be rejected by the endpoint.
        """
        tag_ids = [tag_id_override] if tag_id_override is not None else job.tag_ids
        return RandomSearchPayload(
            size=min(count_override or job.count, RANDOM_SEARCH_MAX_SIZE),
            album_ids=job.album_ids,
            person_ids=job.person_ids,
            tag_ids=tag_ids,
            is_favorite=job.is_favorite,
            city=job.city,
            state=job.state,
            country=job.country,
            taken_after=job.taken_after.isoformat() if job.taken_after else None,
            taken_before=job.taken_before.isoformat() if job.taken_before else None,
            rating=job.rating,
        )

    def _build_smart_payload(
        self,
        job: ImmichJobFilter,
        count_override: int | None = None,
    ) -> SmartSearchPayload:
        """Build payload for smart search from job config."""
        if not job.query:
            raise ValueError("Smart search requires a query string")

        return SmartSearchPayload(
            query=job.query,
            size=count_override or job.count,
            album_ids=job.album_ids,
            person_ids=job.person_ids,
            tag_ids=job.tag_ids,
            is_favorite=job.is_favorite,
            city=job.city,
            state=job.state,
            country=job.country,
            taken_after=job.taken_after.isoformat() if job.taken_after else None,
            taken_before=job.taken_before.isoformat() if job.taken_before else None,
            rating=job.rating,
        )

    async def download_original(self, asset_id: str) -> AsyncIterator[bytes]:
        """Stream download of asset's original file.

        Args:
            asset_id: Asset UUID

        Yields:
            Chunks of file data

        """
        if self._client is None:
            raise RuntimeError("Client not connected")

        async with self._client.stream(
            "GET",
            f"/api/assets/{asset_id}/original",
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                yield chunk

    async def get_asset(self, asset_id: str) -> ImmichAsset:
        """Get full asset details including people data.

        Args:
            asset_id: Asset UUID

        Returns:
            Asset with full details including people/faces

        """
        response = await self._request("GET", f"/api/assets/{asset_id}")
        return ImmichAsset.model_validate(response.json())

    async def get_asset_albums(self, asset_id: str) -> list[ImmichAlbum]:
        """Get albums containing a specific asset.

        Args:
            asset_id: Asset UUID

        Returns:
            List of albums containing this asset

        """
        response = await self._request("GET", "/api/albums", params={"assetId": asset_id})
        return AlbumsResponse.model_validate(response.json()).root
