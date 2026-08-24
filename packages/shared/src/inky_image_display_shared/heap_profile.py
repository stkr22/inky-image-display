"""Opt-in tracemalloc heap profiling shared by the API and the sync worker.

Both services grow their RSS in *steps* that line up with sync batches rather
than with uptime, so the measurement that identifies a leak is a diff across
one batch — not an absolute snapshot. This module keeps a baseline snapshot
and reports the allocations that outlived it, grouped by traceback.

Disabled unless explicitly switched on: tracemalloc retains a traceback for
every live allocation, which is real memory on containers that already sit
close to their limit. Raise the memory limit for the duration of a profiling
run rather than leaving this on.
"""

from __future__ import annotations

import gc
import os
import tracemalloc
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

# Deep enough to cross the ``asyncio.to_thread`` hop in the image-processing
# path and still name the request handler that owns the allocation.
DEFAULT_FRAMES = 15

_MIB = 1024 * 1024
_BASELINE_KEY = "snapshot"

# Single-slot holder rather than a module-level name reassigned through
# ``global`` (ruff PLW0603).
_baseline: dict[str, tracemalloc.Snapshot] = {}


def start(frames: int = DEFAULT_FRAMES) -> None:
    """Begin tracing and record the initial baseline."""
    if not tracemalloc.is_tracing():
        tracemalloc.start(frames)
    capture_baseline()


def stop() -> None:
    """Stop tracing and drop the baseline."""
    _baseline.clear()
    if tracemalloc.is_tracing():
        tracemalloc.stop()


def capture_baseline() -> None:
    """Move the comparison point to now.

    Call this immediately before the operation under investigation to bracket
    a single batch; leave it alone to measure cumulative growth since startup.
    """
    if tracemalloc.is_tracing():
        _baseline[_BASELINE_KEY] = tracemalloc.take_snapshot()


def is_active() -> bool:
    """Whether tracing is currently on."""
    return tracemalloc.is_tracing()


def report(top: int = 25, gc_census: bool = False) -> dict[str, Any]:
    """Summarise retained allocations, largest first.

    With a baseline the entries are deltas against it, which is what isolates
    a per-batch leak from the steady-state heap. ``gc_census`` walks every
    tracked object, so it pauses the process proportionally to heap size —
    off by default.
    """
    if not tracemalloc.is_tracing():
        return {"tracing": False}

    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    baseline = _baseline.get(_BASELINE_KEY)
    payload: dict[str, Any] = {
        "tracing": True,
        "traced_current_bytes": current,
        "traced_peak_bytes": peak,
        "rss_bytes": _rss_bytes(),
        "has_baseline": baseline is not None,
    }

    if baseline is not None:
        payload["top"] = [
            {
                "size_diff_bytes": stat.size_diff,
                "count_diff": stat.count_diff,
                "size_bytes": stat.size,
                "count": stat.count,
                "traceback": stat.traceback.format(),
            }
            for stat in snapshot.compare_to(baseline, "traceback")[:top]
        ]
    else:
        payload["top"] = [
            {
                "size_bytes": stat.size,
                "count": stat.count,
                "traceback": stat.traceback.format(),
            }
            for stat in snapshot.statistics("traceback")[:top]
        ]

    if gc_census:
        payload["gc"] = _gc_census()
    return payload


def log_report(log: logging.Logger, top: int = 10) -> None:
    """Write a report to ``log``, for processes with no HTTP surface."""
    data = report(top=top)
    if not data.get("tracing"):
        return

    rss = data["rss_bytes"]
    log.info(
        "heap: rss=%s traced=%.1fMiB peak=%.1fMiB baseline=%s",
        f"{rss / _MIB:.1f}MiB" if rss is not None else "n/a",
        data["traced_current_bytes"] / _MIB,
        data["traced_peak_bytes"] / _MIB,
        data["has_baseline"],
    )
    for entry in data["top"]:
        size = entry.get("size_diff_bytes", entry.get("size_bytes", 0))
        count = entry.get("count_diff", entry.get("count", 0))
        location = "\n    ".join(entry["traceback"])
        log.info("heap: %+.2fMiB (%+d blocks)\n    %s", size / _MIB, count, location)


def _gc_census(top: int = 25) -> dict[str, Any]:
    """Count live gc-tracked objects by type.

    Blind to ``bytes``/``bytearray`` buffers, which the collector does not
    track — read it alongside the tracemalloc entries, not instead of them.
    """
    counts: dict[str, int] = {}
    for obj in gc.get_objects():
        name = type(obj).__name__
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    return {
        "generation_counts": list(gc.get_count()),
        "uncollectable": len(gc.garbage),
        "top_types": dict(ranked),
    }


def _rss_bytes() -> int | None:
    """Resident set size from procfs, or None where it isn't available."""
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return resident_pages * os.sysconf("SC_PAGE_SIZE")
