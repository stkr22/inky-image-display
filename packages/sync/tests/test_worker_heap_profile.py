"""Tests for the worker's per-cycle heap report."""

import logging

import pytest
from inky_image_display_shared import heap_profile
from inky_image_display_sync.worker import WorkerConfig, _run_cycle


@pytest.fixture(autouse=True)
def _no_tracing_left_behind():
    """Tracing is process-global; never leak it into another test."""
    heap_profile.stop()
    yield
    heap_profile.stop()


def _idle_config(*, profile_heap: bool = False, profile_heap_top: int = 10) -> WorkerConfig:
    """A config whose cycle does nothing but the heap report."""
    return WorkerConfig(
        enable_immich=False,
        enable_gemini=False,
        enable_display=False,
        profile_heap=profile_heap,
        profile_heap_top=profile_heap_top,
    )


async def test_cycle_logs_a_heap_report_while_profiling(caplog: pytest.LogCaptureFixture):
    config = _idle_config(profile_heap=True, profile_heap_top=3)
    heap_profile.start(frames=3)

    with caplog.at_level(logging.INFO, logger="inky_image_display_sync"):
        await _run_cycle(config)

    assert any(record.getMessage().startswith("heap:") for record in caplog.records)


async def test_cycle_stays_quiet_when_profiling_is_off(caplog: pytest.LogCaptureFixture):
    config = _idle_config()

    with caplog.at_level(logging.INFO, logger="inky_image_display_sync"):
        await _run_cycle(config)

    assert not any(record.getMessage().startswith("heap:") for record in caplog.records)
