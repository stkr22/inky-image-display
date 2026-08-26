"""Tests for the Calibre bookshelf job routes.

One lifecycle round-trip rather than a test per endpoint: the sync service and
UI drive these exact sequences, and a round-trip catches the realistic failures
— filters not applied, partial updates clobbering fields, and the JSON filter
columns not surviving persistence.
"""

from uuid import uuid4

from fastapi.testclient import TestClient


def _payload(**overrides) -> dict:
    body = {
        "name": "sunday-shelves",
        "target_device_profile_id": str(uuid4()),
        "prompt_preset_id": str(uuid4()),
        "tags": ["Fantasy", "Science Fiction"],
        "languages": ["deu"],
        "min_rating": 4,
        "books_per_shelf": 6,
        "retention_days": 30,
    }
    body.update(overrides)
    return body


class TestCalibreJobsCrud:
    def test_lifecycle_round_trip(self, client: TestClient):
        created = client.post("/api/calibre/jobs", json=_payload())
        assert created.status_code == 201, created.text
        job = created.json()
        job_id = job["id"]
        # The filter lists are JSON columns; a round-trip is the only thing
        # that proves they persist as lists rather than stringified blobs.
        assert job["tags"] == ["Fantasy", "Science Fiction"]
        assert job["languages"] == ["deu"]
        assert job["min_rating"] == 4
        assert job["mode"] == "shelf"
        assert job["verify_spines"] is True

        listed = client.get("/api/calibre/jobs", params={"is_active": "true"}).json()
        assert [j["id"] for j in listed] == [job_id]

        updated = client.put(f"/api/calibre/jobs/{job_id}", json={"books_per_shelf": 4})
        assert updated.status_code == 200
        assert updated.json()["books_per_shelf"] == 4
        # Partial update must not reset the untouched filter.
        assert updated.json()["tags"] == ["Fantasy", "Science Fiction"]

        assert client.delete(f"/api/calibre/jobs/{job_id}").status_code == 204
        assert client.get(f"/api/calibre/jobs/{job_id}").status_code == 404

    def test_unknown_id_returns_404_on_all_methods(self, client: TestClient):
        missing = uuid4()
        assert client.get(f"/api/calibre/jobs/{missing}").status_code == 404
        assert client.put(f"/api/calibre/jobs/{missing}", json={"books_per_shelf": 4}).status_code == 404
        assert client.post(f"/api/calibre/jobs/{missing}/run-now").status_code == 404
        assert client.delete(f"/api/calibre/jobs/{missing}").status_code == 404

    def test_hero_mode_accepted(self, client: TestClient):
        created = client.post("/api/calibre/jobs", json=_payload(name="daily-hero", mode="hero"))
        assert created.status_code == 201
        assert created.json()["mode"] == "hero"

    def test_unknown_mode_rejected(self, client: TestClient):
        created = client.post("/api/calibre/jobs", json=_payload(name="bad", mode="carousel"))
        assert created.status_code == 422

    def test_out_of_range_rating_rejected(self, client: TestClient):
        assert client.post("/api/calibre/jobs", json=_payload(name="bad", min_rating=9)).status_code == 422


class TestCalibreJobScheduling:
    def test_created_job_is_immediately_due_then_claimed_once(self, client: TestClient):
        created = client.post("/api/calibre/jobs", json=_payload(schedule_cron="0 6 * * 0"))
        assert created.status_code == 201
        job_id = created.json()["id"]

        # A fresh job delivers right away rather than waiting for its first cron.
        due = client.get("/api/calibre/jobs", params={"due": "true"}).json()
        assert [j["id"] for j in due] == [job_id]

        claimed = client.post("/api/calibre/jobs/claim-due").json()
        assert [j["id"] for j in claimed] == [job_id]
        # Claiming advances the schedule, so a second claim hands out nothing.
        assert client.post("/api/calibre/jobs/claim-due").json() == []

    def test_manual_job_is_never_due_until_run_now(self, client: TestClient):
        created = client.post("/api/calibre/jobs", json=_payload(schedule_cron=None))
        job_id = created.json()["id"]
        assert client.get("/api/calibre/jobs", params={"due": "true"}).json() == []

        assert client.post(f"/api/calibre/jobs/{job_id}/run-now").status_code == 200
        due = client.get("/api/calibre/jobs", params={"due": "true"}).json()
        assert [j["id"] for j in due] == [job_id]

    def test_inactive_job_can_still_be_run_now(self, client: TestClient):
        # "Run now" is an operator override; requiring activation first would
        # make testing a paused job impossible.
        created = client.post("/api/calibre/jobs", json=_payload(is_active=False, schedule_cron=None))
        job_id = created.json()["id"]
        client.post(f"/api/calibre/jobs/{job_id}/run-now")
        assert [j["id"] for j in client.post("/api/calibre/jobs/claim-due").json()] == [job_id]
