"""Shared helpers for image-vs-grid quality hints.

Used by both the grid detail page (per-tile resolution badges) and the
upload form (live preview as the user picks a target grid).
"""

from __future__ import annotations

from typing import Any

# Thresholds for the source-resolution traffic light. ``ratio`` is the
# image's effective px/cm divided by the densest member device's px/cm.
RES_RATIO_SHARP = 1.0
RES_RATIO_SOFT = 0.7
# Aspect drift below this fraction is reported as "no crop".
CROP_NEGLIGIBLE = 0.005


def max_device_pxcm(
    grid: dict[str, Any],
    all_devices: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> float | None:
    """Highest px/cm across every device placed on the grid.

    Sets the resolution floor for source images: anything below this rate
    is upscaled on at least one device. Returns ``None`` when the grid has
    no placements or the profile lookup fails.
    """
    placements = grid.get("devices") or []
    if not placements:
        return None
    device_by_id = {d["id"]: d for d in all_devices}
    profile_by_id = {p["id"]: p for p in profiles}
    rates: list[float] = []
    for placement in placements:
        device = device_by_id.get(placement["device_id"])
        if device is None:
            continue
        profile = profile_by_id.get(device["device_profile_id"])
        if profile is None:
            continue
        width_px = profile["height"] if device["display_orientation"] == "portrait" else profile["width"]
        if placement["width_cm"] > 0:
            rates.append(width_px / placement["width_cm"])
    return max(rates) if rates else None


def image_fit(image_w: int | float, image_h: int | float, grid: dict[str, Any]) -> dict[str, Any] | None:
    """Compute aspect drift and effective source px/cm for an image on the grid.

    Mirrors ``grid_service.compute_crop_for_device``: cover-fit picks the
    smaller of ``img_w/grid_w_cm`` and ``img_h/grid_h_cm`` as the resulting
    px/cm rate, and the overflow axis loses content.
    """
    if not image_w or not image_h:
        return None
    grid_w = float(grid["width_cm"])
    grid_h = float(grid["height_cm"])
    canvas_aspect = grid_w / grid_h
    image_aspect = image_w / image_h
    if image_aspect > canvas_aspect:
        used_w = image_h * canvas_aspect
        crop_pct = (image_w - used_w) / image_w
        crop_axis = "horizontal"
        effective_pxcm = image_h / grid_h
    else:
        used_h = image_w / canvas_aspect
        crop_pct = (image_h - used_h) / image_h
        crop_axis = "vertical" if image_aspect < canvas_aspect else "none"
        effective_pxcm = image_w / grid_w
    return {
        "image_aspect": image_aspect,
        "canvas_aspect": canvas_aspect,
        "crop_pct": crop_pct,
        "crop_axis": crop_axis,
        "effective_pxcm": effective_pxcm,
    }


def resolution_band(ratio: float) -> tuple[str, str]:
    """Map effective/required px-rate ratio to a label + colour."""
    if ratio >= RES_RATIO_SHARP:
        return "sharp", "var(--ink-success, #2f855a)"
    if ratio >= RES_RATIO_SOFT:
        return "soft", "var(--ink-warning, #b7791f)"
    return "upscaled", "var(--ink-danger, #c53030)"
