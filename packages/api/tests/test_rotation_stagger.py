"""Tests for staggered rejoin after mass rotations.

When several panels become due in the same tick (a grid release or the end
of quiet hours), they all repaint at once — but each next refresh is
scheduled relative to the previous one, so without correction they would
keep flashing simultaneously every interval. The rotation pass spreads the
next refreshes evenly across the interval; the ``stagger_rotation`` app
setting turns that off.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from inky_image_display_api.services.app_settings_service import set_stagger_rotation
from inky_image_display_api.services.rotation import _rotate_due_devices
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.time import utcnow
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

PAST = datetime(2020, 1, 1, 12, 0, 0)


def _app(async_engine, mock_settings, mock_s3_service, mock_mqtt) -> MagicMock:
    app = MagicMock()
    app.state.engine = async_engine
    app.state.settings = mock_settings
    app.state.s3_service = mock_s3_service
    app.state.mqtt = mock_mqtt
    return app


def _due_device(profile, device_id: str) -> Device:
    return Device(
        id=uuid4(),
        device_id=device_id,
        device_profile_id=profile.id,
        display_orientation="landscape",
        is_online=True,
        scheduled_next_at=PAST,
        last_refresh_ok=True,
    )


def _images(count: int) -> list[Image]:
    return [
        Image(
            id=uuid4(),
            source_name="manual",
            storage_path=f"manual/{i}.jpg",
            original_width=1600,
            original_height=1200,
            is_portrait=False,
        )
        for i in range(count)
    ]


async def _seed(async_engine: AsyncEngine, *rows) -> None:
    async with AsyncSession(async_engine) as session:
        session.add_all(rows)
        await session.commit()


async def _next_offsets(async_engine: AsyncEngine, now) -> list[float]:
    async with AsyncSession(async_engine) as session:
        devices = (await session.exec(select(Device))).all()
    return sorted((d.scheduled_next_at - now).total_seconds() for d in devices)


@pytest.mark.asyncio
async def test_mass_rotation_spreads_next_refreshes_across_the_interval(
    async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
) -> None:
    devices = [_due_device(seed_profile, f"panel-{i}") for i in range(3)]
    await _seed(async_engine, *_images(3), *devices)
    mock_mqtt.is_connected = MagicMock(return_value=True)

    before = utcnow()
    await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

    # 3 panels, 3600 s interval → next refreshes at ~1200/2400/3600 s.
    offsets = await _next_offsets(async_engine, before)
    assert len(offsets) == 3
    for offset, expected in zip(offsets, (1200, 2400, 3600), strict=True):
        assert offset == pytest.approx(expected, abs=5)


@pytest.mark.asyncio
async def test_single_due_device_keeps_its_full_interval(
    async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
) -> None:
    await _seed(async_engine, *_images(1), _due_device(seed_profile, "panel-solo"))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    before = utcnow()
    await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

    offsets = await _next_offsets(async_engine, before)
    assert offsets[0] == pytest.approx(3600, abs=5)


@pytest.mark.asyncio
async def test_disabled_setting_leaves_the_full_interval_for_everyone(
    async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
) -> None:
    async with AsyncSession(async_engine) as session:
        await set_stagger_rotation(session, enabled=False)
    devices = [_due_device(seed_profile, f"panel-{i}") for i in range(2)]
    await _seed(async_engine, *_images(2), *devices)
    mock_mqtt.is_connected = MagicMock(return_value=True)

    before = utcnow()
    await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

    offsets = await _next_offsets(async_engine, before)
    assert len(offsets) == 2
    for offset in offsets:
        assert offset == pytest.approx(3600, abs=5)


@pytest.mark.asyncio
async def test_device_interval_scales_its_own_stagger_slice(
    async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
) -> None:
    # Per-device intervals stagger within their *own* interval, so a
    # short-cadence panel is not pushed out to the fleet default.
    fast = _due_device(seed_profile, "panel-fast")
    fast.refresh_interval_seconds = 600
    slow = _due_device(seed_profile, "panel-slow")
    await _seed(async_engine, *_images(2), fast, slow)
    mock_mqtt.is_connected = MagicMock(return_value=True)

    before = utcnow()
    await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

    async with AsyncSession(async_engine) as session:
        devices = (await session.exec(select(Device))).all()
    offsets = {d.device_id: (d.scheduled_next_at - before).total_seconds() for d in devices}
    # Each lands at interval * (index + 1) / 2; whichever slot the fast
    # panel got, its offset derives from its 600 s interval.
    assert offsets["panel-fast"] in (pytest.approx(300, abs=5), pytest.approx(600, abs=5))
    assert offsets["panel-slow"] in (pytest.approx(1800, abs=5), pytest.approx(3600, abs=5))
