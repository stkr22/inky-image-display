"""Tests for Immich sync job CRUD — focused on album/person match modes.

The modes decide whether the worker keeps Immich's native AND across
multiple ids or emulates OR by unioning per-id queries, so persisting and
validating them correctly is what protects the operator's intent.
"""

from fastapi.testclient import TestClient


def _job_body(seed_profile, **overrides) -> dict:
    body = {"name": "match-mode-job", "target_device_profile_id": str(seed_profile.id)}
    body.update(overrides)
    return body


class TestSyncJobMatchModes:
    def test_create_defaults_to_all(self, client: TestClient, seed_profile) -> None:
        """Existing behaviour (AND) must stay the default for new jobs."""
        response = client.post("/api/sync-jobs", json=_job_body(seed_profile))
        assert response.status_code == 201
        created = response.json()
        assert created["album_match_mode"] == "all"
        assert created["person_match_mode"] == "all"

    def test_create_with_any_roundtrips(self, client: TestClient, seed_profile) -> None:
        response = client.post(
            "/api/sync-jobs",
            json=_job_body(
                seed_profile,
                name="any-mode-job",
                album_ids=["a1", "a2"],
                album_match_mode="any",
                person_match_mode="any",
            ),
        )
        assert response.status_code == 201
        job_id = response.json()["id"]

        fetched = client.get(f"/api/sync-jobs/{job_id}").json()
        assert fetched["album_match_mode"] == "any"
        assert fetched["person_match_mode"] == "any"

    def test_update_switches_mode(self, client: TestClient, seed_profile) -> None:
        created = client.post("/api/sync-jobs", json=_job_body(seed_profile, name="update-mode-job")).json()

        response = client.put(f"/api/sync-jobs/{created['id']}", json={"person_match_mode": "any"})
        assert response.status_code == 200
        assert response.json()["person_match_mode"] == "any"
        # Untouched sibling keeps its value.
        assert response.json()["album_match_mode"] == "all"

    def test_invalid_mode_rejected(self, client: TestClient, seed_profile) -> None:
        response = client.post(
            "/api/sync-jobs",
            json=_job_body(seed_profile, name="bad-mode-job", album_match_mode="or"),
        )
        assert response.status_code == 422
