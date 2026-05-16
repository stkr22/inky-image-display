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

    async def list_images(  # noqa: PLR0913 — pass-through filters mirror the API params
        self,
        *,
        source_name: str | None = None,
        is_portrait: bool | None = None,
        target_grid_id: UUID | str | None = None,
        solo_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List images with optional source/orientation/grid filters and pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if source_name is not None:
            params["source_name"] = source_name
        if is_portrait is not None:
            params["is_portrait"] = is_portrait
        if target_grid_id is not None:
            params["target_grid_id"] = str(target_grid_id)
        if solo_only:
            params["solo_only"] = True
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

    # --- Device profiles ---

    async def list_device_profiles(self) -> list[dict[str, Any]]:
        """List the seeded device profiles."""
        response = await self._client.get("/api/device-profiles")
        return _parse_json_list(response)

    async def update_device_profile(self, profile_id: UUID, *, name: str) -> dict[str, Any]:
        """Update the display name of a profile."""
        response = await self._client.patch(
            f"/api/device-profiles/{profile_id}",
            json={"name": name},
        )
        return _parse_json_dict(response)

    async def set_default_device_profile(self, profile_id: UUID) -> dict[str, Any]:
        """Make the given profile the global genai default."""
        response = await self._client.post(f"/api/device-profiles/{profile_id}/set-default")
        return _parse_json_dict(response)

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

    # --- Prompt blocks ---

    async def list_prompt_blocks(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        """List prompt blocks, optionally filtered by ``kind``."""
        params: dict[str, Any] = {}
        if kind is not None:
            params["kind"] = kind
        response = await self._client.get("/api/genai/blocks", params=params)
        return _parse_json_list(response)

    async def create_prompt_block(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Create a prompt block."""
        response = await self._client.post("/api/genai/blocks", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_prompt_block(self, block_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Patch a prompt block."""
        response = await self._client.put(f"/api/genai/blocks/{block_id}", json=_json_safe(body))
        return _parse_json_dict(response)

    async def delete_prompt_block(self, block_id: UUID) -> None:
        """Delete a prompt block by UUID."""
        response = await self._client.delete(f"/api/genai/blocks/{block_id}")
        _raise_for_status(response)

    # --- Prompt presets ---

    async def list_prompt_presets(self) -> list[dict[str, Any]]:
        """List all prompt presets."""
        response = await self._client.get("/api/genai/presets")
        return _parse_json_list(response)

    async def get_prompt_preset(self, preset_id: UUID) -> dict[str, Any]:
        """Fetch a prompt preset by UUID."""
        response = await self._client.get(f"/api/genai/presets/{preset_id}")
        return _parse_json_dict(response)

    async def create_prompt_preset(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Create a prompt preset."""
        response = await self._client.post("/api/genai/presets", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_prompt_preset(self, preset_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Patch a prompt preset."""
        response = await self._client.put(f"/api/genai/presets/{preset_id}", json=_json_safe(body))
        return _parse_json_dict(response)

    async def delete_prompt_preset(self, preset_id: UUID) -> None:
        """Delete a prompt preset by UUID."""
        response = await self._client.delete(f"/api/genai/presets/{preset_id}")
        _raise_for_status(response)

    # --- Gemini sync jobs ---

    async def list_gemini_jobs(self, *, is_active: bool | None = None) -> list[dict[str, Any]]:
        """List Gemini sync jobs, optionally filtered by ``is_active``."""
        params: dict[str, Any] = {}
        if is_active is not None:
            params["is_active"] = is_active
        response = await self._client.get("/api/genai/jobs", params=params)
        return _parse_json_list(response)

    async def get_gemini_job(self, job_id: UUID) -> dict[str, Any]:
        """Fetch a Gemini sync job by UUID."""
        response = await self._client.get(f"/api/genai/jobs/{job_id}")
        return _parse_json_dict(response)

    async def create_gemini_job(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Create a Gemini sync job."""
        response = await self._client.post("/api/genai/jobs", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_gemini_job(self, job_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Patch a Gemini sync job."""
        response = await self._client.put(f"/api/genai/jobs/{job_id}", json=_json_safe(body))
        return _parse_json_dict(response)

    async def delete_gemini_job(self, job_id: UUID) -> None:
        """Delete a Gemini sync job by UUID."""
        response = await self._client.delete(f"/api/genai/jobs/{job_id}")
        _raise_for_status(response)

    # --- Grids ---

    async def list_grids(self, *, include_devices: bool = False) -> list[dict[str, Any]]:
        """List grids, optionally embedding device placements."""
        params: dict[str, Any] = {}
        if include_devices:
            params["include_devices"] = include_devices
        response = await self._client.get("/api/grids", params=params)
        return _parse_json_list(response)

    async def get_grid(self, grid_id: UUID) -> dict[str, Any]:
        """Fetch a single grid by UUID (with placements)."""
        response = await self._client.get(f"/api/grids/{grid_id}")
        return _parse_json_dict(response)

    async def create_grid(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Create a new grid from a ``GridCreate``-shaped dict."""
        response = await self._client.post("/api/grids", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_grid(self, grid_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Patch a grid's name or dimensions."""
        response = await self._client.put(f"/api/grids/{grid_id}", json=_json_safe(body))
        return _parse_json_dict(response)

    async def delete_grid(self, grid_id: UUID) -> None:
        """Delete a grid (cascades placements; clears image targets)."""
        response = await self._client.delete(f"/api/grids/{grid_id}")
        _raise_for_status(response)

    async def add_device_to_grid(self, grid_id: UUID, body: Mapping[str, Any]) -> dict[str, Any]:
        """Place a device on the grid using a midpoint or explicit corner."""
        response = await self._client.post(f"/api/grids/{grid_id}/devices", json=_json_safe(body))
        return _parse_json_dict(response)

    async def update_device_placement(
        self,
        grid_id: UUID,
        device_id: UUID,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Move a placed device to a new midpoint or corner."""
        response = await self._client.put(
            f"/api/grids/{grid_id}/devices/{device_id}",
            json=_json_safe(body),
        )
        return _parse_json_dict(response)

    async def remove_device_from_grid(self, grid_id: UUID, device_id: UUID) -> None:
        """Remove a device's placement from the grid."""
        response = await self._client.delete(f"/api/grids/{grid_id}/devices/{device_id}")
        _raise_for_status(response)

    async def display_grid_image(self, grid_id: UUID, image_id: UUID) -> dict[str, Any]:
        """Render slices and push a specific image to every member device."""
        response = await self._client.post(
            f"/api/grids/{grid_id}/display",
            json={"image_id": str(image_id)},
        )
        return _parse_json_dict(response)

    async def release_grid(self, grid_id: UUID) -> dict[str, Any]:
        """Release every claim this grid holds; members return to solo."""
        response = await self._client.post(f"/api/grids/{grid_id}/release")
        return _parse_json_dict(response)

    # --- On-demand image generation ---

    async def generate_image(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Enqueue a Gemini generation; returns ``{task_id, status}``."""
        response = await self._client.post("/api/genai/generate", json=_json_safe(body))
        return _parse_json_dict(response)


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
