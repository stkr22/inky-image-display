"""Tests for the gated heap-profiling endpoints."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from inky_image_display_shared import heap_profile


@pytest.fixture
def enabled(mock_settings: MagicMock) -> Iterator[None]:
    """Flag on and tracing armed, torn down whatever the test does.

    Tracing is process-global, so leaving it on would tax every later test.
    """
    mock_settings.profile_heap = True
    heap_profile.start(frames=5)
    try:
        yield
    finally:
        heap_profile.stop()


@pytest.fixture
def flag_only(mock_settings: MagicMock) -> Iterator[None]:
    """Flag on but tracing never started."""
    mock_settings.profile_heap = True
    heap_profile.stop()
    yield
    heap_profile.stop()


class TestDisabled:
    """With API_PROFILE_HEAP unset the routes must not exist."""

    def test_get_heap_is_404(self, client: TestClient):
        assert client.get("/api/debug/heap").status_code == 404

    def test_reset_baseline_is_404(self, client: TestClient):
        assert client.post("/api/debug/heap/baseline").status_code == 404


class TestEnabled:
    """With profiling on the report describes the live heap."""

    def test_report_has_expected_shape(self, client: TestClient, enabled: None):
        resp = client.get("/api/debug/heap")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tracing"] is True
        assert body["has_baseline"] is True
        assert body["traced_current_bytes"] > 0
        assert isinstance(body["top"], list)

    def test_report_attributes_a_deliberate_allocation(self, client: TestClient, enabled: None):
        client.post("/api/debug/heap/baseline")
        # ~4 MiB that outlives the report, so it must show up as growth.
        blob = [bytes(200_000) for _ in range(20)]

        resp = client.get("/api/debug/heap", params={"top": 50})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_baseline"] is True
        frames = "\n".join("".join(entry["traceback"]) for entry in body["top"])
        assert "test_debug_heap.py" in frames
        assert len(blob) == 20

    def test_top_bounds_the_result(self, client: TestClient, enabled: None):
        resp = client.get("/api/debug/heap", params={"top": 3})
        assert resp.status_code == 200
        assert len(resp.json()["top"]) <= 3

    def test_top_must_be_positive(self, client: TestClient, enabled: None):
        assert client.get("/api/debug/heap", params={"top": 0}).status_code == 422

    def test_gc_census_is_opt_in(self, client: TestClient, enabled: None):
        assert "gc" not in client.get("/api/debug/heap").json()

        body = client.get("/api/debug/heap", params={"gc_census": "true"}).json()

        assert body["gc"]["uncollectable"] == 0
        assert body["gc"]["top_types"]

    def test_baseline_reset_moves_the_comparison_point(self, client: TestClient, enabled: None):
        keep = [bytes(200_000) for _ in range(20)]
        assert client.post("/api/debug/heap/baseline").json() == {"status": "baseline reset"}

        body = client.get("/api/debug/heap", params={"top": 50}).json()

        # The pre-baseline blob is now steady state, not growth.
        growth = sum(entry["size_diff_bytes"] for entry in body["top"] if entry["size_diff_bytes"] > 0)
        assert growth < len(keep) * 200_000


class TestEnabledButNotTracing:
    """Defensive: the flag is read per request, tracing is set up at boot."""

    def test_report_says_it_is_not_tracing(self, client: TestClient, flag_only: None):
        resp = client.get("/api/debug/heap")
        assert resp.status_code == 200
        assert resp.json() == {"tracing": False}

    def test_baseline_reset_conflicts(self, client: TestClient, flag_only: None):
        assert client.post("/api/debug/heap/baseline").status_code == 409
