"""Tests for the genai CRUD routes (prompt blocks + Gemini sync jobs).

One lifecycle round-trip per resource instead of a test per endpoint: the
sync service and UI drive these exact sequences, and a round-trip catches
the realistic failures (filters not applied, partial updates clobbering
fields, the JSON ``subjects`` column not surviving persistence).
"""

from uuid import uuid4

from fastapi.testclient import TestClient


class TestPromptBlocksCrud:
    def test_lifecycle_round_trip(self, client: TestClient):
        created = client.post(
            "/api/genai/blocks",
            json={"kind": "style", "name": "bold", "text": "Bold {subject}"},
        )
        assert created.status_code == 201
        block_id = created.json()["id"]

        # The kind filter must include the new block and exclude other kinds.
        listed = client.get("/api/genai/blocks", params={"kind": "style"}).json()
        assert [b["id"] for b in listed] == [block_id]
        assert client.get("/api/genai/blocks", params={"kind": "palette"}).json() == []

        got = client.get(f"/api/genai/blocks/{block_id}")
        assert got.status_code == 200
        assert got.json()["text"] == "Bold {subject}"

        updated = client.put(f"/api/genai/blocks/{block_id}", json={"text": "Subtle {subject}"})
        assert updated.status_code == 200
        assert updated.json()["text"] == "Subtle {subject}"
        assert updated.json()["name"] == "bold"  # partial update keeps other fields

        assert client.delete(f"/api/genai/blocks/{block_id}").status_code == 204
        assert client.get(f"/api/genai/blocks/{block_id}").status_code == 404

    def test_unknown_id_returns_404_on_all_methods(self, client: TestClient):
        missing = uuid4()
        assert client.get(f"/api/genai/blocks/{missing}").status_code == 404
        assert client.put(f"/api/genai/blocks/{missing}", json={"text": "x"}).status_code == 404
        assert client.delete(f"/api/genai/blocks/{missing}").status_code == 404


class TestGeminiSyncJobsCrud:
    def test_lifecycle_round_trip(self, client: TestClient):
        created = client.post(
            "/api/genai/jobs",
            json={
                "name": "daily-portraits",
                "target_device_profile_id": str(uuid4()),
                "prompt_preset_id": str(uuid4()),
                "subjects": ["a fox", "a heron"],
                "images_per_subject": 2,
                "retention_days": 7,
            },
        )
        assert created.status_code == 201
        body = created.json()
        job_id = body["id"]
        # The subjects list lives in a JSON column — it must survive persistence.
        assert body["subjects"] == ["a fox", "a heron"]
        assert body["orientation"] == "portrait"  # default

        # is_active filter: new jobs are active by default.
        active = client.get("/api/genai/jobs", params={"is_active": True}).json()
        assert [j["id"] for j in active] == [job_id]
        assert client.get("/api/genai/jobs", params={"is_active": False}).json() == []

        updated = client.put(
            f"/api/genai/jobs/{job_id}",
            json={"is_active": False, "subjects": ["a bear"]},
        )
        assert updated.status_code == 200
        assert updated.json()["is_active"] is False
        assert updated.json()["subjects"] == ["a bear"]
        assert updated.json()["images_per_subject"] == 2  # untouched field preserved

        # The deactivated job moves to the other side of the filter.
        inactive = client.get("/api/genai/jobs", params={"is_active": False}).json()
        assert [j["id"] for j in inactive] == [job_id]

        assert client.delete(f"/api/genai/jobs/{job_id}").status_code == 204
        assert client.get(f"/api/genai/jobs/{job_id}").status_code == 404

    def test_unknown_id_returns_404_on_all_methods(self, client: TestClient):
        missing = uuid4()
        assert client.get(f"/api/genai/jobs/{missing}").status_code == 404
        assert client.put(f"/api/genai/jobs/{missing}", json={"name": "x"}).status_code == 404
        assert client.delete(f"/api/genai/jobs/{missing}").status_code == 404
