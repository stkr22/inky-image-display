"""Tests for the genai CRUD routes (prompt blocks, Gemini and Calibre sync jobs).

One lifecycle round-trip per resource instead of a test per endpoint: the
sync service and UI drive these exact sequences, and a round-trip catches
the realistic failures (filters not applied, partial updates clobbering
fields, the JSON ``subjects`` column not surviving persistence).
"""

from uuid import uuid4

import pytest
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


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/genai/blocks/{id}", None),
        ("PUT", "/api/genai/blocks/{id}", {"text": "x"}),
        ("DELETE", "/api/genai/blocks/{id}", None),
        ("GET", "/api/genai/jobs/{id}", None),
        ("PUT", "/api/genai/jobs/{id}", {"name": "x"}),
        ("DELETE", "/api/genai/jobs/{id}", None),
        ("GET", "/api/calibre/jobs/{id}", None),
        ("PUT", "/api/calibre/jobs/{id}", {"books_per_shelf": 4}),
        ("POST", "/api/calibre/jobs/{id}/run-now", None),
        ("DELETE", "/api/calibre/jobs/{id}", None),
    ],
)
def test_unknown_id_is_404(client: TestClient, method: str, path: str, body: dict | None):
    """A stale id from an open UI tab must be a 404, not a 500 or a silent no-op."""
    response = client.request(method, path.format(id=uuid4()), json=body)
    assert response.status_code == 404
