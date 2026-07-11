"""Tests for sync run reporting and the run-now flow."""

from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from inky_image_display_shared.models import ImmichSyncJob, SyncJobRun
from inky_image_display_shared.time import utcnow
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


def _report(job_id: UUID, *, status: str = "success", started_offset: int = 0) -> dict:
    started = utcnow() + timedelta(seconds=started_offset)
    return {
        "job_type": "immich",
        "job_id": str(job_id),
        "job_name": "holiday-photos",
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": (started + timedelta(seconds=5)).isoformat(),
        "images_added": 3,
        "images_skipped": 2,
        "images_deleted": 1,
        "detail": "SyncResult(...)",
        "error": "boom" if status == "error" else None,
    }


async def _seed_job(async_engine: AsyncEngine, seed_profile, **kwargs) -> ImmichSyncJob:
    job = ImmichSyncJob(name=kwargs.pop("name", "holiday-photos"), target_device_profile_id=seed_profile.id, **kwargs)
    async with AsyncSession(async_engine) as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


class TestSyncRunReporting:
    async def test_report_and_list_roundtrip(self, client: TestClient, async_engine, seed_profile) -> None:
        job = await _seed_job(async_engine, seed_profile)
        response = client.post("/api/sync-runs", json=_report(job.id))
        assert response.status_code == 201

        listed = client.get("/api/sync-runs", params={"job_id": str(job.id)})
        assert listed.status_code == 200
        body = listed.json()
        assert len(body) == 1
        assert body[0]["job_name"] == "holiday-photos"
        assert body[0]["images_added"] == 3
        assert body[0]["status"] == "success"

    async def test_report_clears_run_request_flag(self, client: TestClient, async_engine, seed_profile) -> None:
        job = await _seed_job(async_engine, seed_profile, run_requested_at=utcnow() - timedelta(minutes=1))
        client.post("/api/sync-runs", json=_report(job.id))
        async with AsyncSession(async_engine) as session:
            result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job.id))
            assert result.one().run_requested_at is None

    async def test_stale_report_does_not_clear_newer_request(
        self, client: TestClient, async_engine, seed_profile
    ) -> None:
        """A run that started before the click must not consume the click."""
        job = await _seed_job(async_engine, seed_profile, run_requested_at=utcnow())
        client.post("/api/sync-runs", json=_report(job.id, started_offset=-3600))
        async with AsyncSession(async_engine) as session:
            result = await session.exec(select(ImmichSyncJob).where(col(ImmichSyncJob.id) == job.id))
            assert result.one().run_requested_at is not None

    async def test_history_is_pruned_per_job(self, client: TestClient, async_engine, seed_profile) -> None:
        job = await _seed_job(async_engine, seed_profile)
        for i in range(25):
            client.post("/api/sync-runs", json=_report(job.id, started_offset=i * 60))
        async with AsyncSession(async_engine) as session:
            result = await session.exec(select(SyncJobRun).where(SyncJobRun.job_id == job.id))
            assert len(result.all()) == 20


class TestRunNow:
    async def test_run_now_flags_job_and_requested_filter_finds_it(
        self, client: TestClient, async_engine, seed_profile
    ) -> None:
        job = await _seed_job(async_engine, seed_profile, is_active=False)

        assert client.get("/api/sync-jobs", params={"requested": "true"}).json() == []

        response = client.post(f"/api/sync-jobs/{job.id}/run-now")
        assert response.status_code == 200
        assert response.json()["run_requested_at"] is not None

        requested = client.get("/api/sync-jobs", params={"requested": "true"}).json()
        assert [j["id"] for j in requested] == [str(job.id)]

    def test_run_now_unknown_job_is_404(self, client: TestClient) -> None:
        assert client.post(f"/api/sync-jobs/{uuid4()}/run-now").status_code == 404
