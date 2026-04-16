"""Tests for the health endpoint."""

from fastapi.testclient import TestClient


class TestHealth:
    """Tests for GET /health."""

    def test_returns_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
