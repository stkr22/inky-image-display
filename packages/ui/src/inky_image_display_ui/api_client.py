"""Async HTTP client for the inky-image-display-api service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEVICE_NOT_CONNECTED_DETAIL = "Device not connected"


class ApiError(Exception):
    """Raised when the upstream API returns a non-2xx response.

    Attributes:
        status_code: HTTP status code returned by the API.
        detail: Parsed ``detail`` field from the API error body, when present.

    """

    def __init__(self, status_code: int, detail: str | None) -> None:
        """Initialise with the upstream status code and parsed detail."""
        super().__init__(f"API returned {status_code}: {detail or '<no detail>'}")
        self.status_code = status_code
        self.detail = detail


class DeviceNotConnectedError(ApiError):
    """Raised when a device command targets a device without an active WebSocket."""


class ApiClient:
    """Thin async wrapper over the inky-image-display-api REST surface.

    The wrapper holds a long-lived :class:`httpx.AsyncClient` so TCP
    connections are reused across the many small requests the Flet views
    make.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Initialise with a pre-configured :class:`httpx.AsyncClient`.

        The client is expected to have ``base_url`` and ``timeout`` already set.
        """
        self._client = client

    # --- Images ---

    async def list_images(
        self,
        *,
        source_name: str | None = None,
        is_portrait: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List images with optional source/orientation filters and pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if source_name is not None:
            params["source_name"] = source_name
        if is_portrait is not None:
            params["is_portrait"] = is_portrait
        response = await self._client.get("/api/images", params=params)
        return _parse_json_list(response)

    async def get_image(self, image_id: UUID) -> dict[str, Any]:
        """Fetch a single image by UUID."""
        response = await self._client.get(f"/api/images/{image_id}")
        return _parse_json_dict(response)

    async def upload_image(
        self,
        file_bytes: bytes,
        filename: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Upload an image file plus a JSON metadata blob matching ``ImageCreate``.

        The API expects ``multipart/form-data`` with a ``file`` part and a
        ``metadata`` form field containing a JSON string.
        """
        files = {"file": (filename, file_bytes)}
        data = {"metadata": json.dumps(dict(metadata))}
        response = await self._client.post("/api/images", files=files, data=data)
        return _parse_json_dict(response)

    async def update_image(self, image_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Update image metadata via PUT /api/images/{id}."""
        response = await self._client.put(
            f"/api/images/{image_id}",
            json=_json_safe(body),
        )
        return _parse_json_dict(response)

    async def delete_image(self, image_id: UUID) -> None:
        """Delete an image (DB row + S3 object)."""
        response = await self._client.delete(f"/api/images/{image_id}")
        _raise_for_status(response)

    # --- Devices ---

    async def list_devices(
        self,
        *,
        room: str | None = None,
        is_online: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List devices with optional room and online-status filters."""
        params: dict[str, Any] = {}
        if room is not None:
            params["room"] = room
        if is_online is not None:
            params["is_online"] = is_online
        response = await self._client.get("/api/devices", params=params)
        return _parse_json_list(response)

    async def get_device(self, device_id: str) -> dict[str, Any]:
        """Fetch a single device by its string identifier."""
        response = await self._client.get(f"/api/devices/{device_id}")
        return _parse_json_dict(response)

    async def display_image(self, device_id: str, image_id: UUID) -> None:
        """Command a device to display a specific image."""
        response = await self._client.post(
            f"/api/devices/{device_id}/display",
            json={"image_id": str(image_id)},
        )
        _raise_for_status(response, device_command=True)

    async def next_image(self, device_id: str) -> dict[str, Any]:
        """Ask the API to pick and push the FIFO next image for a device."""
        response = await self._client.post(f"/api/devices/{device_id}/next")
        _raise_for_status(response, device_command=True)
        return response.json()

    async def clear_device(self, device_id: str) -> None:
        """Command a device to clear its current display."""
        response = await self._client.post(f"/api/devices/{device_id}/clear")
        _raise_for_status(response, device_command=True)

    # --- Sync jobs ---

    async def list_sync_jobs(self, *, is_active: bool | None = None) -> list[dict[str, Any]]:
        """List sync jobs with an optional active-only filter."""
        params: dict[str, Any] = {}
        if is_active is not None:
            params["is_active"] = is_active
        response = await self._client.get("/api/sync-jobs", params=params)
        return _parse_json_list(response)

    async def get_sync_job(self, job_id: UUID) -> dict[str, Any]:
        """Fetch a single sync job by UUID."""
        response = await self._client.get(f"/api/sync-jobs/{job_id}")
        return _parse_json_dict(response)

    async def create_sync_job(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Create a new sync job from an ``SyncJobCreate``-shaped dict."""
        response = await self._client.post("/api/sync-jobs", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_sync_job(self, job_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Update a sync job with an ``SyncJobUpdate``-shaped dict."""
        response = await self._client.put(
            f"/api/sync-jobs/{job_id}",
            json=_json_safe(body),
        )
        return _parse_json_dict(response)

    async def delete_sync_job(self, job_id: UUID) -> None:
        """Delete a sync job by UUID."""
        response = await self._client.delete(f"/api/sync-jobs/{job_id}")
        _raise_for_status(response)


def _parse_json_list(response: httpx.Response) -> list[dict[str, Any]]:
    """Raise on non-2xx and return the JSON body as a list of dicts."""
    _raise_for_status(response)
    return response.json()


def _parse_json_dict(response: httpx.Response) -> dict[str, Any]:
    """Raise on non-2xx and return the JSON body as a dict."""
    _raise_for_status(response)
    return response.json()


def _raise_for_status(response: httpx.Response, *, device_command: bool = False) -> None:
    """Turn non-2xx responses into :class:`ApiError` (or subclass)."""
    if response.is_success:
        return
    detail = _extract_detail(response)
    if device_command and response.status_code == httpx.codes.NOT_FOUND and detail == _DEVICE_NOT_CONNECTED_DETAIL:
        raise DeviceNotConnectedError(response.status_code, detail)
    raise ApiError(response.status_code, detail)


def _extract_detail(response: httpx.Response) -> str | None:
    """Pull the ``detail`` field from a JSON error body, best-effort."""
    try:
        body = response.json()
    except ValueError:
        return response.text or None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
    return None


def _json_safe(body: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort conversion of non-JSON-native values (UUIDs, datetimes) to strings."""
    out: dict[str, Any] = {}
    for key, value in body.items():
        out[key] = _coerce(value)
    return out


def _coerce(value: Any) -> Any:
    """Recursively convert UUIDs/datetimes to JSON-safe primitives."""
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_coerce(item) for item in value]
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    return value
