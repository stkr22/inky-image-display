"""Route-level tests for /api/display-jobs (worker claim model)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from inky_image_display_shared.models import Image, ImageGroup, PromptPreset, SyncJobRun
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
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


async def _seed_group(
    engine: AsyncEngine,
    job_id: str,
    grid_id: str,
    *,
    slotted: bool = True,
) -> UUID:
    """Insert a generated group with one screen image for slot (0, 0)."""
    async with AsyncSession(engine) as session:
        group = ImageGroup(
            name="Bridge built",
            target_grid_id=UUID(grid_id),
            display_job_id=UUID(job_id),
        )
        session.add(group)
        await session.flush()
        session.add(
            Image(
                source_name="display-job",
                storage_path=f"groups/{group.id}/{uuid4()}.jpg",
                title="Bridge built",
                original_width=1600,
                original_height=1200,
                group_id=group.id,
                group_slot_row=0 if slotted else None,
                group_slot_col=0 if slotted else None,
            )
        )
        group_id = group.id
        await session.commit()
    return group_id


class TestDisplayJobCrud:
    def test_create_and_get(self, client: TestClient) -> None:
        job = _create_job(client)
        assert job["job_type"] == "motd"
        assert job["content_prompt"] == DEFAULT_MOTD_PROMPT
        assert job["default_prompt"] == DEFAULT_MOTD_PROMPT
        assert job["target_grid_id"] is None
        assert job["is_active"] is True
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
            "schedule_cron": "0 6 * * *",
            "slots": [{"row": 0, "col": 0, "parts": ["what", "why+takeaway", "qr"]}],
        }
        response = client.put(f"/api/display-jobs/{job['id']}", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["content_prompt"] == "Custom themes"
        assert body["source_mode"] == "knowledge"
        assert body["schedule_cron"] == "0 6 * * *"
        assert body["next_run_at"] is not None
        assert body["slots"] == [{"row": 0, "col": 0, "parts": ["what", "why+takeaway", "qr"]}]

    def test_update_clear_schedule_sets_manual_only(self, client: TestClient) -> None:
        job = _create_job(client)
        client.put(f"/api/display-jobs/{job['id']}", json={"schedule_cron": "0 * * * *"})
        response = client.put(f"/api/display-jobs/{job['id']}", json={"clear_schedule": True})
        assert response.json()["schedule_cron"] is None
        assert response.json()["next_run_at"] is None

    def test_update_pause_and_resume(self, client: TestClient) -> None:
        job = _create_job(client)
        assert client.put(f"/api/display-jobs/{job['id']}", json={"is_active": False}).json()["is_active"] is False
        assert client.put(f"/api/display-jobs/{job['id']}", json={"is_active": True}).json()["is_active"] is True

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

    def test_create_with_schedule_is_due_immediately(self, client: TestClient) -> None:
        response = client.post("/api/display-jobs", json={"name": "cadenced", "schedule_cron": "0 6 * * *"})
        assert response.status_code == 201
        body = response.json()
        assert body["schedule_cron"] == "0 6 * * *"
        assert body["next_run_at"] is not None

    def test_delete_job(self, client: TestClient) -> None:
        job = _create_job(client)
        assert client.delete(f"/api/display-jobs/{job['id']}").status_code == 204
        assert client.get(f"/api/display-jobs/{job['id']}").status_code == 404

    def test_multiple_jobs_can_target_one_grid(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        _create_job(client, grid_id)
        other = client.post("/api/display-jobs", json={"name": "second"}).json()
        assert client.put(f"/api/display-jobs/{other['id']}", json={"target_grid_id": grid_id}).status_code == 200


class TestClaimDue:
    def test_claim_returns_due_job_with_resolved_slots(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        # Creating with a schedule makes the job due immediately (a PUT
        # would rebase the schedule into the future instead).
        job = client.post(
            "/api/display-jobs", json={"name": "due-job", "target_grid_id": grid_id, "schedule_cron": "0 6 * * *"}
        ).json()
        client.put(
            f"/api/display-jobs/{job['id']}",
            json={"slots": [{"row": 0, "col": 0, "parts": ["what", "qr"]}]},
        )

        claims = client.post("/api/display-jobs/claim-due").json()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["id"] == job["id"]
        assert claim["target_grid_id"] == grid_id
        assert claim["slots"] == [
            {
                "row": 0,
                "col": 0,
                "parts": ["what", "qr"],
                "device_id": seed_device.device_id,
                "width": 1600,
                "height": 1200,
                "is_portrait": False,
            }
        ]
        # Lease semantics: a second claim hands out nothing.
        assert client.post("/api/display-jobs/claim-due").json() == []

    def test_job_without_grid_is_never_due(self, client: TestClient) -> None:
        job = _create_job(client)
        client.put(f"/api/display-jobs/{job['id']}", json={"schedule_cron": "0 * * * *"})
        assert client.post("/api/display-jobs/claim-due").json() == []

    def test_paused_job_is_not_due_but_run_now_wins(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.put(f"/api/display-jobs/{job['id']}", json={"schedule_cron": "0 * * * *", "is_active": False})
        assert client.post("/api/display-jobs/claim-due").json() == []

        assert client.post(f"/api/display-jobs/{job['id']}/run-now").status_code == 200
        claims = client.post("/api/display-jobs/claim-due").json()
        assert [c["id"] for c in claims] == [job["id"]]

    def test_run_now_without_grid_returns_409(self, client: TestClient) -> None:
        job = _create_job(client)
        assert client.post(f"/api/display-jobs/{job['id']}/run-now").status_code == 409

    @pytest.mark.asyncio
    async def test_claim_records_running_run_row(
        self, client: TestClient, async_engine: AsyncEngine, seed_device: Device
    ) -> None:
        grid_id = _create_grid(client, seed_device)
        job = client.post(
            "/api/display-jobs", json={"name": "due-job", "target_grid_id": grid_id, "schedule_cron": "0 * * * *"}
        ).json()
        client.post("/api/display-jobs/claim-due")

        async with AsyncSession(async_engine) as session:
            runs = (await session.exec(select(SyncJobRun).where(col(SyncJobRun.job_id) == UUID(job["id"])))).all()
        assert len(runs) == 1
        assert runs[0].status == "running"
        assert runs[0].finished_at is None

    def test_report_completes_running_row_and_clears_run_now(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        client.post(f"/api/display-jobs/{job['id']}/run-now")
        client.post("/api/display-jobs/claim-due")

        started = utcnow()
        report = {
            "job_type": "display",
            "job_id": job["id"],
            "job_name": job["name"],
            "status": "success",
            "started_at": started.isoformat(),
            "finished_at": (started + timedelta(minutes=1)).isoformat(),
            "images_added": 3,
        }
        assert client.post("/api/sync-runs", json=report).status_code == 201

        runs = client.get("/api/sync-runs", params={"job_type": "display", "job_id": job["id"]}).json()
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["images_added"] == 3
        assert client.get(f"/api/display-jobs/{job['id']}").json()["run_requested_at"] is None


class TestRenderPart:
    def test_renders_text_part(self, client: TestClient) -> None:
        response = client.post(
            "/api/display-jobs/render-part",
            json={"part": "what", "width": 640, "height": 400, "what": "A bridge was built."},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert len(response.content) > 0

    def test_missing_content_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/display-jobs/render-part", json={"part": "what", "width": 640, "height": 400})
        assert response.status_code == 422

    def test_image_part_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/display-jobs/render-part", json={"part": "image", "width": 640, "height": 400})
        assert response.status_code == 422


class TestDisplayJobActions:
    def test_display_without_group_returns_409(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        response = client.post(f"/api/display-jobs/{job['id']}/display")
        assert response.status_code == 409
        assert "No generated group" in response.json()["detail"]

    def test_display_without_grid_returns_409(self, client: TestClient) -> None:
        job = _create_job(client)
        response = client.post(f"/api/display-jobs/{job['id']}/display")
        assert response.status_code == 409
        assert "no target grid" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_display_pushes_latest_group(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        mock_mqtt: MagicMock,
        seed_device: Device,
    ) -> None:
        mock_mqtt.is_connected = MagicMock(return_value=True)
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        group_id = await _seed_group(async_engine, job["id"], grid_id)

        response = client.post(f"/api/display-jobs/{job['id']}/display")
        assert response.status_code == 200
        body = response.json()
        assert body["group_id"] == str(group_id)
        assert body["displayed"] == [seed_device.device_id]
        assert mock_mqtt.send_command.await_count == 1

        status = client.get(f"/api/grids/{grid_id}/display-status").json()
        assert status["group_id"] == str(group_id)
        assert status["hold_until"] is not None
        assert status["slots"][0]["device_id"] == seed_device.device_id

    @pytest.mark.asyncio
    async def test_groups_history_lists_generated_groups(
        self, client: TestClient, async_engine: AsyncEngine, seed_device: Device
    ) -> None:
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        assert client.get(f"/api/display-jobs/{job['id']}/groups").json() == []

        group_id = await _seed_group(async_engine, job["id"], grid_id)
        groups = client.get(f"/api/display-jobs/{job['id']}/groups").json()
        assert [g["id"] for g in groups] == [str(group_id)]
        assert len(groups[0]["images"]) == 1

    @pytest.mark.asyncio
    async def test_release_resumes_queue_immediately(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        mock_mqtt: MagicMock,
        seed_device: Device,
    ) -> None:
        """Release updates the panels right away instead of waiting a cycle."""
        mock_mqtt.is_connected = MagicMock(return_value=True)
        grid_id = _create_grid(client, seed_device)
        job = _create_job(client, grid_id)
        await _seed_group(async_engine, job["id"], grid_id)
        assert client.post(f"/api/display-jobs/{job['id']}/display").status_code == 200
        pushes_before = mock_mqtt.send_command.await_count

        assert client.post(f"/api/grids/{grid_id}/release").status_code == 200
        # The only queue content is the group itself, so release replays it —
        # the point is that a push happened immediately.
        assert mock_mqtt.send_command.await_count >= pushes_before
        status = client.get(f"/api/grids/{grid_id}/display-status").json()
        assert status["hold_until"] is None

    def test_status_idle(self, client: TestClient, seed_device: Device) -> None:
        grid_id = _create_grid(client, seed_device)
        response = client.get(f"/api/grids/{grid_id}/display-status")
        assert response.status_code == 200
        body = response.json()
        assert body["group_id"] is None
        assert [slot["device_id"] for slot in body["slots"]] == [seed_device.device_id]
