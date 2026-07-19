"""Route-level tests for /api/display-jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from inky_image_display_shared.models import MotdMessage, MotdScreen, PromptPreset
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from inky_image_display_shared.models import Device
    from sqlalchemy.ext.asyncio import AsyncEngine


def _create_grid(client: TestClient, device: Device, name: str = "wall") -> str:
    response = client.post("/api/grids", json={"name": name, "rows": [[str(device.id)]]})
    assert response.status_code == 201
    return response.json()["id"]


def _create_job(client: TestClient, grid_id: str | None = None, name: str = "morning-motd") -> dict:
    body: dict = {"name": name}
    if grid_id is not None:
        body["target_grid_id"] = grid_id
    response = client.post("/api/display-jobs", json=body)
    assert response.status_code == 201
    return response.json()


class TestDisplayJobCrud:
    def test_create_and_get(self, client: TestClient) -> None:
        job = _create_job(client)
        assert job["job_type"] == "motd"
        assert job["content_prompt"] == DEFAULT_MOTD_PROMPT
        assert job["default_prompt"] == DEFAULT_MOTD_PROMPT
        assert job["target_grid_id"] is None
        assert job["slots"] == []

        fetched = client.get(f"/api/display-jobs/{job['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "morning-motd"
        assert [j["id"] for j in client.get("/api/display-jobs").json()] == [job["id"]]

    @pytest.mark.asyncio
    async def test_create_defaults_to_scene_preset(self, client: TestClient, async_engine: AsyncEngine) -> None:
        """A new MOTD job picks the seeded scene preset when present."""
        block_id = uuid4()
        async with AsyncSession(async_engine) as session:
            session.add(
                PromptPreset(
                    id=uuid4(),
                    name="e_ink_scene",
                    style_block_id=block_id,
                    palette_block_id=block_id,
                    legibility_block_id=block_id,
                    composition_block_id=block_id,
                    background_block_id=block_id,
                    is_default=False,
                )
            )
            await session.commit()
            preset_id = (await session.exec(select(PromptPreset))).one().id

        job = _create_job(client)
        assert job["image_preset_id"] == str(preset_id)

    def test_update_round_trip_with_slots(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        payload = {
            "content_prompt": "Custom themes",
            "source_mode": "knowledge",
            "schedule_enabled": True,
            "display_time": "07:30",
            "weekday_mask": 31,
            "timezone": "Europe/Berlin",
            "generation_lead_minutes": 45,
            "display_duration_seconds": 3600,
            "slots": [{"row": 0, "col": 0, "parts": ["what", "why+takeaway", "qr"]}],
        }
        response = client.put(f"/api/display-jobs/{job['id']}", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["content_prompt"] == "Custom themes"
        assert body["source_mode"] == "knowledge"
        assert body["display_time"] == "07:30"
        assert body["timezone"] == "Europe/Berlin"
        assert body["display_duration_seconds"] == 3600
        assert body["slots"] == [{"row": 0, "col": 0, "parts": ["what", "why+takeaway", "qr"], "rotation_index": 0}]

    def test_update_clear_duration_sets_indefinite(self, client: TestClient) -> None:
        job = _create_job(client)
        client.put(f"/api/display-jobs/{job['id']}", json={"display_duration_seconds": 600})
        response = client.put(f"/api/display-jobs/{job['id']}", json={"clear_display_duration": True})
        assert response.json()["display_duration_seconds"] is None

    def test_update_rejects_invalid_part(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.put(
            f"/api/display-jobs/{job['id']}",
            json={"slots": [{"row": 0, "col": 0, "parts": ["what", "banana"]}]},
        )
        assert response.status_code == 422
        assert "banana" in response.text

    def test_update_rejects_non_text_compound(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.put(
            f"/api/display-jobs/{job['id']}",
            json={"slots": [{"row": 0, "col": 0, "parts": ["image+qr"]}]},
        )
        assert response.status_code == 422

    def test_update_rejects_duplicate_slot(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.put(
            f"/api/display-jobs/{job['id']}",
            json={
                "slots": [
                    {"row": 0, "col": 0, "parts": ["what"]},
                    {"row": 0, "col": 0, "parts": ["why"]},
                ]
            },
        )
        assert response.status_code == 422

    def test_update_rejects_bad_timezone_and_time(self, client: TestClient) -> None:
        job = _create_job(client)
        assert client.put(f"/api/display-jobs/{job['id']}", json={"timezone": "Mars/Olympus"}).status_code == 422
        assert client.put(f"/api/display-jobs/{job['id']}", json={"display_time": "25:00"}).status_code == 422

    def test_delete_job(self, client: TestClient) -> None:
        job = _create_job(client)
        assert client.delete(f"/api/display-jobs/{job['id']}").status_code == 204
        assert client.get(f"/api/display-jobs/{job['id']}").status_code == 404

    @pytest.mark.asyncio
    async def test_slot_edits_resync_active_session(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        mock_mqtt: MagicMock,
        mock_s3_service: MagicMock,
        seed_device: Device,
    ) -> None:
        """Slot edits made while a session is active take effect immediately."""
        mock_mqtt.is_connected = MagicMock(return_value=True)
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.put(f"/api/display-jobs/{job['id']}", json={"slots": [{"row": 0, "col": 0, "parts": ["what"]}]})
        async with AsyncSession(async_engine) as session:
            message = MotdMessage(
                job_id=UUID(job["id"]),
                status="ready",
                headline="Bridge built",
                what="A bridge.",
                takeaway="Build bridges.",
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            session.add(
                MotdScreen(
                    message_id=message.id,
                    part="what",
                    width=1600,
                    height=1200,
                    is_portrait=False,
                    storage_path=f"motd/{message.id}/what_1600x1200.jpg",
                )
            )
            await session.commit()
        assert client.post(f"/api/display-jobs/{job['id']}/display").status_code == 200
        assert mock_mqtt.send_command.await_count == 1

        response = client.put(
            f"/api/display-jobs/{job['id']}",
            json={"slots": [{"row": 0, "col": 0, "parts": ["takeaway"]}]},
        )

        assert response.status_code == 200
        # The takeaway screen did not exist — rendered on demand and pushed.
        assert mock_mqtt.send_command.await_count == 2
        command = mock_mqtt.send_command.await_args.args[1]
        assert command.image_path.endswith("takeaway_1600x1200.jpg")
        mock_s3_service.upload_image.assert_called_once()
        status = client.get(f"/api/display-jobs/{job['id']}/status").json()
        assert status["slots"][0]["current_part"] == "takeaway"

    def test_changing_grid_during_active_session_is_409(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.put(f"/api/display-jobs/{job['id']}", json={"slots": [{"row": 0, "col": 0, "parts": ["what"]}]})
        # No active session: retargeting is fine (also proves the guard is scoped).
        other = client.post("/api/display-jobs", json={"name": "second"}).json()
        assert client.put(f"/api/display-jobs/{other['id']}", json={"target_grid_id": grid_id}).status_code == 200


class TestDisplayJobActions:
    def test_generate_without_api_key_returns_503(self, client: TestClient, mock_settings: MagicMock) -> None:
        mock_settings.gemini_api_key = None
        job = _create_job(client)
        response = client.post(f"/api/display-jobs/{job['id']}/generate")
        assert response.status_code == 503

    def test_display_without_message_returns_409(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.put(f"/api/display-jobs/{job['id']}", json={"slots": [{"row": 0, "col": 0, "parts": ["what"]}]})
        response = client.post(f"/api/display-jobs/{job['id']}/display")
        assert response.status_code == 409
        assert "No generated message" in response.json()["detail"]

    def test_display_without_grid_returns_409(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.post(f"/api/display-jobs/{job['id']}/display")
        assert response.status_code == 409
        assert "no target grid" in response.json()["detail"]

    def test_display_unknown_message_returns_409(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        response = client.post(
            f"/api/display-jobs/{job['id']}/display",
            json={"message_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert response.status_code == 409
        assert "no longer exists" in response.json()["detail"]

    def test_release_is_idempotent(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.post(f"/api/display-jobs/{job['id']}/release")
        assert response.status_code == 200
        assert response.json() == {"status": "released"}

    def test_status_inactive(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.get(f"/api/display-jobs/{job['id']}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["slots"] == []

    def test_messages_list_empty(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.get(f"/api/display-jobs/{job['id']}/messages")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_grid_manual_display_blocked_during_session(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        mock_mqtt: MagicMock,
        seed_device: Device,
    ) -> None:
        """While a job session holds the grid, manual pool pushes 409."""
        mock_mqtt.is_connected = MagicMock(return_value=True)
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.put(f"/api/display-jobs/{job['id']}", json={"slots": [{"row": 0, "col": 0, "parts": ["what"]}]})
        async with AsyncSession(async_engine) as session:
            message = MotdMessage(job_id=UUID(job["id"]), status="ready", headline="x", what="y")
            session.add(message)
            await session.commit()
            await session.refresh(message)
            session.add(
                MotdScreen(
                    message_id=message.id,
                    part="what",
                    width=1600,
                    height=1200,
                    is_portrait=False,
                    storage_path=f"motd/{message.id}/what_1600x1200.jpg",
                )
            )
            await session.commit()
        assert client.post(f"/api/display-jobs/{job['id']}/display").status_code == 200

        response = client.post(f"/api/grids/{grid_id}/next")
        assert response.status_code == 409
        assert "display job session" in response.json()["detail"]

        # After release, the grid is usable again (404 = empty pool, not 409).
        client.post(f"/api/display-jobs/{job['id']}/release")
        assert client.post(f"/api/grids/{grid_id}/next").status_code == 404
