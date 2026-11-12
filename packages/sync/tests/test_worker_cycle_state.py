"""Tests for what the long-running worker keeps between cycles."""

from unittest.mock import AsyncMock, patch

import pytest
from inky_image_display_sync.worker import CycleState, WorkerConfig, _run_cycle


def _calibre_only() -> WorkerConfig:
    return WorkerConfig(enable_immich=False, enable_gemini=False, enable_display=False, enable_calibre=True)


async def test_calibre_client_and_its_catalog_cache_survive_between_cycles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CALIBRE_BASE_URL", "http://calibre.invalid")
    state = CycleState()
    run_calibre = AsyncMock()

    with patch("inky_image_display_sync.main.run_calibre_sync", run_calibre):
        await _run_cycle(_calibre_only(), state)
        await _run_cycle(_calibre_only(), state)

    first, second = (call.kwargs["calibre"] for call in run_calibre.await_args_list)
    assert first is second is state.calibre


async def test_calibre_misconfiguration_only_fails_the_calibre_family(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CALIBRE_BASE_URL", raising=False)
    run_calibre = AsyncMock()

    with patch("inky_image_display_sync.main.run_calibre_sync", run_calibre):
        await _run_cycle(_calibre_only(), CycleState())  # must not raise

    run_calibre.assert_not_awaited()
