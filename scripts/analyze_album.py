"""Analyze an Immich album or person for Inky e-ink display suitability.

Fetches every asset, scores each image against the Inky 6-color Spectra palette,
and emits a CSV row per asset (sortable in any spreadsheet) flagging resolution
and aspect-ratio problems.

Usage:

    IMMICH_API_KEY=... uv run python scripts/analyze_album.py \\
        --base-url https://immich.example.com --album <album_id> --output report.csv

``--base-url`` can also be supplied via the ``IMMICH_BASE_URL`` env var.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from io import BytesIO

import httpx
import numpy as np  # ty: ignore[unresolved-import]  # script-only dep, intentionally not in project pyproject
import pillow_heif
from PIL import Image

# iPhone albums frequently contain HEIC originals; registering the opener
# lets PIL.Image.open transparently decode them.
pillow_heif.register_heif_opener()

# Inky Impression Spectra 6 palette (the 6 ink colours the panel can render).
# Used as the quantisation target for the palette-fit score.
INKY_PALETTE = np.array(
    [
        (0, 0, 0),  # black
        (255, 255, 255),  # white
        (255, 0, 0),  # red
        (0, 255, 0),  # green
        (0, 0, 255),  # blue
        (255, 255, 0),  # yellow
    ],
    dtype=np.float32,
)

# Thresholds for flagging issues; chosen as conservative defaults that match
# user-visible problems on the panel (washed-out images, hard crops).
LOW_SATURATION = 0.20
LOW_PALETTE_FIT = 0.60
ASPECT_TOLERANCE = 0.10  # 10% deviation from target aspect


@dataclass
class AssetReport:
    index: int
    asset_id: str
    filename: str
    width: int
    height: int
    orientation: str
    aspect: float
    saturation: float
    palette_fit: float
    issues: list[str]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze an Immich album or person's photos for Inky display suitability.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--album", help="Immich album UUID")
    src.add_argument("--person", help="Immich person UUID")
    p.add_argument("--width", type=int, default=1600, help="Target panel width (default: 1600)")
    p.add_argument("--height", type=int, default=1200, help="Target panel height (default: 1200)")
    p.add_argument("--output", help="Write CSV to file instead of stdout")
    p.add_argument(
        "--base-url",
        default=os.environ.get("IMMICH_BASE_URL"),
        help="Immich base URL (or set IMMICH_BASE_URL)",
    )
    args = p.parse_args()
    if not args.base_url:
        p.error("--base-url is required (or set IMMICH_BASE_URL)")
    return args


def orientation_of(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def palette_fit_score(rgb: np.ndarray) -> float:
    """Mean per-pixel distance to nearest Inky palette colour, inverted to 0..1.

    Why: e-ink panels physically can't render colours between palette anchors,
    so images far from those anchors look muddy after dithering.
    """
    pixels = rgb.reshape(-1, 3).astype(np.float32)
    # Subsample large images to keep runtime bounded; 50k pixels gives stable
    # estimates within ~1% of full-image scores.
    if pixels.shape[0] > 50_000:
        idx = np.random.default_rng(0).choice(pixels.shape[0], 50_000, replace=False)
        pixels = pixels[idx]
    # Squared distance to each palette colour; pick the minimum.
    diff = pixels[:, None, :] - INKY_PALETTE[None, :, :]
    sq = np.sum(diff * diff, axis=2)
    nearest = np.sqrt(sq.min(axis=1))
    # Max possible distance in RGB space is sqrt(3) * 255; normalise then invert.
    mean_err = float(nearest.mean()) / (np.sqrt(3) * 255)
    return 1.0 - mean_err


def mean_saturation(rgb: np.ndarray) -> float:
    img = Image.fromarray(rgb).convert("HSV")
    sat = np.asarray(img)[..., 1].astype(np.float32) / 255.0
    return float(sat.mean())


def analyze_image(data: bytes) -> tuple[int, int, float, float]:
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGB")
        w, h = img.size
        # Originals can be 24MP+; downsample before scoring. The colour stats
        # we care about are stable at low resolution, and this keeps the
        # per-image work bounded.
        scoring = img.copy()
        scoring.thumbnail((1024, 1024))
        arr = np.asarray(scoring)
    return w, h, mean_saturation(arr), palette_fit_score(arr)


def compute_issues(
    width: int,
    height: int,
    saturation: float,
    palette_fit: float,
    target_w: int,
    target_h: int,
) -> list[str]:
    issues: list[str] = []

    # Compare against the target as orientation-agnostic (long-edge vs long-edge).
    long_target = max(target_w, target_h)
    short_target = min(target_w, target_h)
    long_img = max(width, height)
    short_img = min(width, height)

    if long_img < long_target or short_img < short_target:
        issues.append(f"low-res ({width}x{height} < {target_w}x{target_h})")

    img_aspect = long_img / short_img
    target_aspect = long_target / short_target
    if abs(img_aspect - target_aspect) / target_aspect > ASPECT_TOLERANCE:
        issues.append(f"aspect {img_aspect:.2f} vs {target_aspect:.2f}")

    if saturation < LOW_SATURATION:
        issues.append(f"low saturation ({saturation:.2f})")
    if palette_fit < LOW_PALETTE_FIT:
        issues.append(f"poor palette fit ({palette_fit:.2f})")
    return issues


def fetch_album(client: httpx.Client, album_id: str) -> dict:
    resp = client.get(f"/api/albums/{album_id}")
    resp.raise_for_status()
    return resp.json()


def fetch_person_assets(client: httpx.Client, person_id: str) -> tuple[str, list[dict]]:
    """Return (person_name, assets) for every image tagged with this person.

    /api/search/metadata is paginated; follow nextPage until None. We force
    type=IMAGE server-side so we don't have to filter videos out later.
    """
    # /api/people/{id} for the display name; falls back to the UUID if the
    # key lacks people.read.
    name_resp = client.get(f"/api/people/{person_id}")
    name = (name_resp.json().get("name") or person_id) if name_resp.status_code == 200 else person_id

    assets: list[dict] = []
    page: int | None = 1
    while page is not None:
        resp = client.post(
            "/api/search/metadata",
            json={"personIds": [person_id], "type": "IMAGE", "page": page, "size": 250},
        )
        resp.raise_for_status()
        block = resp.json().get("assets", {})
        assets.extend(block.get("items", []))
        next_page = block.get("nextPage")
        page = int(next_page) if next_page else None
    return name, assets


def fetch_image(client: httpx.Client, asset_id: str) -> bytes:
    # The /thumbnail endpoint requires a permission this read-only API key
    # doesn't carry (returns 403), so we pull /original. PIL downsamples
    # internally before scoring to keep this fast.
    resp = client.get(f"/api/assets/{asset_id}/original")
    resp.raise_for_status()
    return resp.content


CSV_FIELDS = (
    "index",
    "filename",
    "asset_id",
    "width",
    "height",
    "orientation",
    "aspect",
    "saturation",
    "palette_fit",
    "issues",
    "link",
)


def write_csv(reports: list[AssetReport], stream, base_url: str) -> None:
    writer = csv.writer(stream)
    writer.writerow(CSV_FIELDS)
    for r in reports:
        writer.writerow(
            [
                r.index,
                r.filename,
                r.asset_id,
                r.width,
                r.height,
                r.orientation,
                f"{r.aspect:.3f}",
                f"{r.saturation:.3f}",
                f"{r.palette_fit:.3f}",
                # Pipe-separated so the cell stays one column but multiple
                # issues remain parseable; spreadsheets can split on '|' later.
                " | ".join(r.issues),
                f"{base_url}/photos/{r.asset_id}",
            ]
        )


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("IMMICH_API_KEY")
    if not api_key:
        print("ERROR: IMMICH_API_KEY not set", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    reports: list[AssetReport] = []

    with httpx.Client(
        base_url=base_url,
        headers={"x-api-key": api_key, "Accept": "application/json"},
        timeout=60.0,
    ) as client:
        if args.album:
            album = fetch_album(client, args.album)
            # Albums can contain videos and live-photo siblings; only IMAGE
            # assets are renderable on the panel, so drop everything else.
            assets = [a for a in album.get("assets", []) if a.get("type") == "IMAGE"]
            source_label = f"album '{album.get('albumName', args.album)}'"
        else:
            name, assets = fetch_person_assets(client, args.person)
            source_label = f"person '{name}'"
        print(f"Analyzing {len(assets)} image assets from {source_label}...", file=sys.stderr)

        for i, asset in enumerate(assets, start=1):
            asset_id = asset["id"]
            filename = asset.get("originalFileName", asset_id)
            try:
                data = fetch_image(client, asset_id)
                w, h, sat, fit = analyze_image(data)
            except Exception as exc:
                print(f"  [{i}/{len(assets)}] {asset_id}: FAILED ({exc})", file=sys.stderr)
                continue

            issues = compute_issues(w, h, sat, fit, args.width, args.height)
            reports.append(
                AssetReport(
                    index=i,
                    asset_id=asset_id,
                    filename=filename,
                    width=w,
                    height=h,
                    orientation=orientation_of(w, h),
                    aspect=max(w, h) / min(w, h),
                    saturation=sat,
                    palette_fit=fit,
                    issues=issues,
                )
            )
            print(f"  [{i}/{len(assets)}] {filename}: sat={sat:.2f} fit={fit:.2f}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            write_csv(reports, f, base_url)
        print(f"Wrote {args.output} ({len(reports)} rows from {source_label})", file=sys.stderr)
    else:
        write_csv(reports, sys.stdout, base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
