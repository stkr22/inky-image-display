"""End-to-end smoke test for the grid feature.

Spins up the API and two mock-display controllers, exercises the full grid
display path against the local Mosquitto + Garage services from the dev
compose stack, and verifies each controller received and "rendered" its
slice.

Run from inside the devcontainer (where ``mosquitto`` and ``garage`` resolve):

    uv run python scripts/e2e_grid.py
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
from PIL import Image, ImageDraw

API_URL = "http://localhost:8000"
MQTT_HOST = "mosquitto"
S3_HOST = "garage:3900"


def _check_service(host: str, port: int, label: str) -> None:
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, port))
    except OSError as exc:
        print(f"[FAIL] {label} unreachable at {host}:{port} — {exc}")
        sys.exit(2)
    finally:
        sock.close()
    print(f"[ok]   {label} reachable at {host}:{port}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def _wait_for(url: str, *, timeout: float = 30.0, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.is_success:
                print(f"[ok]   {label} ready at {url}")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"{label} never became ready at {url}")


def _spawn_api(workdir: Path, log_path: Path, port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "API_DATABASE_PATH": str(workdir / "inky.db"),
            "API_S3_ENDPOINT": S3_HOST,
            "API_S3_BUCKET": "inky-images",
            "API_S3_SECURE": "false",
            "API_S3_REGION": "garage",
            "API_S3_WRITER_ACCESS_KEY": os.environ["API_S3_WRITER_ACCESS_KEY"],
            "API_S3_WRITER_SECRET_KEY": os.environ["API_S3_WRITER_SECRET_KEY"],
            "API_S3_READER_ACCESS_KEY": os.environ["API_S3_READER_ACCESS_KEY"],
            "API_S3_READER_SECRET_KEY": os.environ["API_S3_READER_SECRET_KEY"],
            "API_MQTT_HOST": MQTT_HOST,
            "API_MQTT_PORT": "1883",
            "API_DEVICE_MQTT_HOST": MQTT_HOST,
            "API_DEVICE_MQTT_PORT": "1883",
            "API_DEVICE_MQTT_TLS": "false",
            "API_DEVICE_MQTT_TRANSPORT": "tcp",
        }
    )
    log_file = log_path.open("wb")
    return subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "inky_image_display_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _spawn_controller(
    device_id: str,
    profile_key: str,
    api_url: str,
    log_path: Path,
) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "CONTROLLER_API__URL": api_url,
            "CONTROLLER_DEVICE__ID": device_id,
            "CONTROLLER_DISPLAY__MOCK": "true",
            "CONTROLLER_DISPLAY__MOCK_PROFILE_KEY": profile_key,
            "CONTROLLER_DISPLAY__ORIENTATION": "landscape",
        }
    )
    log_file = log_path.open("wb")
    return subprocess.Popen(
        ["uv", "run", "inky-image-display-controller"],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=2)


def _wait_until_online(client: httpx.Client, expected_device_ids: set[str], timeout: float = 45.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    last_seen: list[dict] = []
    while time.monotonic() < deadline:
        response = client.get("/api/devices")
        response.raise_for_status()
        devices = response.json()
        last_seen = devices
        online_ids = {d["device_id"] for d in devices if d.get("is_online") and d["device_id"] in expected_device_ids}
        if online_ids == expected_device_ids:
            return devices
        time.sleep(1.0)
    raise TimeoutError(f"Devices never came online. Last state: {last_seen}")


def _make_panorama(width: int, height: int) -> bytes:
    """Build a recognisable JPEG so per-device crops have inspectable content."""
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    band_count = 8
    band_height = height // band_count
    palette = [
        (220, 60, 60),
        (220, 140, 50),
        (220, 200, 50),
        (90, 180, 80),
        (60, 150, 200),
        (90, 100, 200),
        (170, 80, 200),
        (60, 60, 60),
    ]
    for i, colour in enumerate(palette):
        draw.rectangle(((0, i * band_height), (width, (i + 1) * band_height)), fill=colour)
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def _wait_for_ack(
    client: httpx.Client,
    device_id: str,
    expected_image_id: str,
    timeout: float = 30.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/devices/{device_id}")
        response.raise_for_status()
        device = response.json()
        if device.get("current_image_id") == expected_image_id:
            return device
        time.sleep(0.5)
    raise TimeoutError(f"Device {device_id} never acked image {expected_image_id}")


def run() -> None:  # noqa: PLR0915 — scripted recipe; readability beats decomposition
    """Run the grid end-to-end smoke test against the dev-compose stack."""
    _check_service(MQTT_HOST, 1883, "Mosquitto")
    host, _, port_s = S3_HOST.partition(":")
    _check_service(host, int(port_s), "Garage")

    workdir = Path(tempfile.mkdtemp(prefix="e2e_grid_"))
    log_dir = workdir / "logs"
    log_dir.mkdir()
    api_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"

    api_proc: subprocess.Popen[bytes] | None = None
    controllers: list[subprocess.Popen[bytes]] = []

    try:
        print(f"[step] launching API on port {api_port} (workdir={workdir})")
        api_proc = _spawn_api(workdir, log_dir / "api.log", api_port)
        _wait_for(f"{api_url}/health", timeout=30, label="API")

        client = httpx.Client(base_url=api_url, timeout=10.0)

        device_specs = [
            ("inky-mock-a", "inky_impression_13_spectra6", 20.0, 20.0),  # 27.1 x 20.3 cm
            ("inky-mock-b", "inky_impression_7_spectra6", 60.0, 25.0),  # 16.3 x 9.8 cm
        ]
        for device_id, profile_key, _, _ in device_specs:
            print(f"[step] launching controller {device_id} ({profile_key})")
            controllers.append(_spawn_controller(device_id, profile_key, api_url, log_dir / f"{device_id}.log"))

        expected_ids = {spec[0] for spec in device_specs}
        print(f"[step] waiting for {expected_ids} to register + come online")
        devices = _wait_until_online(client, expected_ids)
        device_by_id = {d["device_id"]: d for d in devices}

        print("[step] creating grid")
        create = client.post(
            "/api/grids",
            json={"name": "e2e-wall", "width_cm": 80.0, "height_cm": 40.0},
        )
        create.raise_for_status()
        grid = create.json()
        grid_id = grid["id"]

        for device_id, _, mid_x, mid_y in device_specs:
            print(f"[step] placing {device_id} at midpoint ({mid_x}, {mid_y})")
            place = client.post(
                f"/api/grids/{grid_id}/devices",
                json={
                    "device_id": device_by_id[device_id]["id"],
                    "midpoint_x_cm": mid_x,
                    "midpoint_y_cm": mid_y,
                },
            )
            place.raise_for_status()

        print("[step] uploading panorama image targeting the grid")
        panorama = _make_panorama(2400, 800)
        upload = client.post(
            "/api/images",
            files={"file": ("panorama.jpg", panorama, "image/jpeg")},
            data={
                "metadata": json.dumps(
                    {
                        "source_name": "manual",
                        "title": "E2E panorama",
                        "target_grid_id": grid_id,
                    }
                )
            },
        )
        upload.raise_for_status()
        image = upload.json()
        image_id = image["id"]
        assert image["target_grid_id"] == grid_id, "image not assigned to grid"

        print("[step] triggering grid display")
        display = client.post(f"/api/grids/{grid_id}/display", json={"image_id": image_id})
        display.raise_for_status()

        for device_id, _, _, _ in device_specs:
            print(f"[step] waiting for {device_id} ack")
            device = _wait_for_ack(client, device_id, image_id)
            assert UUID(device["claimed_by_grid_id"]) == UUID(grid_id), f"{device_id} not claimed"

        print("[step] checking S3 for per-device slices")
        from minio import Minio  # noqa: PLC0415

        s3 = Minio(
            S3_HOST,
            access_key=os.environ["API_S3_READER_ACCESS_KEY"],
            secret_key=os.environ["API_S3_READER_SECRET_KEY"],
            secure=False,
            region="garage",
        )
        for device_id, _, _, _ in device_specs:
            dev_uuid = device_by_id[device_id]["id"]
            object_key = f"grids/{grid_id}/{image_id}/{dev_uuid}.jpg"
            stat = s3.stat_object("inky-images", object_key)
            size = stat.size or 0
            assert size > 0, f"empty slice at {object_key}"
            print(f"[ok]   slice {object_key} ({size} bytes)")

        print("[step] releasing claims")
        client.post(f"/api/grids/{grid_id}/release").raise_for_status()
        released = client.get("/api/devices").json()
        assert all(d.get("claimed_by_grid_id") is None for d in released), "claims not cleared"

        print("\n[PASS] grid E2E succeeded")
    finally:
        print("[step] tearing down processes")
        for ctrl in controllers:
            _stop(ctrl)
        _stop(api_proc)
        # Keep logs on success only if a debug env var is set; otherwise clean up.
        if os.environ.get("E2E_KEEP_LOGS"):
            print(f"[info] logs retained at {log_dir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    run()
