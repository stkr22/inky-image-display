"""Tests for the device-health gate on automatic image dispatch.

A stuck panel keeps acking and stays "online", so the scheduler must not keep
pushing fresh images at it. Rotation (solo + grid) and GenAI dispatch all skip
devices whose last refresh failed *recently*; a never-acked device
(last_refresh_ok is None) stays eligible. Recovery is automatic two ways: a
success ack clears the flag, and a failure older than the configured backoff
expires — the controller-side retry lives only in device memory, so a
controller restart or a lost success ack must not halt dispatch forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_api.services.generation_service import generate_and_publish
from inky_image_display_api.services.rotation import _rotate_due_devices, _rotate_single_grid
from inky_image_display_shared.models import Device, DeviceProfile, Grid, GridDevice, Image, PromptBlock, PromptPreset
from inky_image_display_shared.time import utcnow
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

PAST = datetime(2020, 1, 1, 12, 0, 0)
# Older than the 900 s backoff configured in mock_settings.
STALE_ERROR_AT = utcnow() - timedelta(seconds=3600)


async def _seed_default_preset(engine: AsyncEngine) -> None:
    """Insert a minimal default prompt preset so generation can resolve one."""
    blocks = [
        PromptBlock(id=uuid4(), kind=kind, name=f"{kind}-default", text=f"{kind} text", is_default=True)
        for kind in ("style", "palette", "legibility", "composition", "background")
    ]
    preset = PromptPreset(
        id=uuid4(),
        name="default",
        style_block_id=blocks[0].id,
        palette_block_id=blocks[1].id,
        legibility_block_id=blocks[2].id,
        composition_block_id=blocks[3].id,
        background_block_id=blocks[4].id,
        is_default=True,
    )
    async with AsyncSession(engine) as session:
        session.add_all([*blocks, preset])
        await session.commit()


def _app(async_engine: AsyncEngine, mock_settings, mock_s3_service, mock_mqtt) -> MagicMock:
    app = MagicMock()
    app.state.engine = async_engine
    app.state.settings = mock_settings
    app.state.s3_service = mock_s3_service
    app.state.mqtt = mock_mqtt
    return app


async def _add(async_engine: AsyncEngine, *rows) -> None:
    async with AsyncSession(async_engine) as session:
        session.add_all(rows)
        await session.commit()


def _due_device(
    profile: DeviceProfile,
    device_id: str,
    *,
    last_refresh_ok: bool | None,
    last_error_at: datetime | None = None,
) -> Device:
    # Acks record last_refresh_ok and last_error_at together, so a failed
    # device defaults to a *recent* error (the blocked case) unless a test
    # pins an explicit timestamp to exercise backoff expiry.
    if last_refresh_ok is False and last_error_at is None:
        last_error_at = utcnow()
    return Device(
        id=uuid4(),
        device_id=device_id,
        device_profile_id=profile.id,
        display_orientation="landscape",
        is_online=True,
        scheduled_next_at=PAST,
        last_refresh_ok=last_refresh_ok,
        last_error_at=last_error_at,
    )


def _landscape_image() -> Image:
    return Image(
        id=uuid4(),
        source_name="manual",
        storage_path="manual/x.jpg",
        original_width=1600,
        original_height=1200,
        is_portrait=False,
    )


class TestSoloRotationGate:
    @pytest.mark.asyncio
    async def test_errored_device_is_skipped_healthy_one_rotates(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        healthy = _due_device(seed_profile, "healthy", last_refresh_ok=True)
        errored = _due_device(seed_profile, "errored", last_refresh_ok=False)
        await _add(async_engine, _landscape_image(), healthy, errored)
        mock_mqtt.is_connected = MagicMock(return_value=True)

        await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

        pushed = {call.args[0] for call in mock_mqtt.send_command.call_args_list}
        assert pushed == {"healthy"}

    @pytest.mark.asyncio
    async def test_never_acked_device_stays_eligible(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        fresh = _due_device(seed_profile, "fresh", last_refresh_ok=None)
        await _add(async_engine, _landscape_image(), fresh)
        mock_mqtt.is_connected = MagicMock(return_value=True)

        await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

        assert {call.args[0] for call in mock_mqtt.send_command.call_args_list} == {"fresh"}

    @pytest.mark.asyncio
    async def test_stale_error_expires_and_device_rotates_again(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        # The failure flag outlived the controller's in-memory retry (e.g. the
        # device was power-cycled) — after the backoff the gate must let go.
        stale = _due_device(seed_profile, "stale", last_refresh_ok=False, last_error_at=STALE_ERROR_AT)
        await _add(async_engine, _landscape_image(), stale)
        mock_mqtt.is_connected = MagicMock(return_value=True)

        await _rotate_due_devices(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt))

        assert {call.args[0] for call in mock_mqtt.send_command.call_args_list} == {"stale"}


class TestGridRotationGate:
    @pytest.mark.asyncio
    async def test_grid_paused_when_a_member_is_errored(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        grid = Grid(id=uuid4(), name="wall", width_cm=80.0, height_cm=40.0, scheduled_next_at=PAST)
        member = _due_device(seed_profile, "grid-member", last_refresh_ok=False)
        placement = GridDevice(
            grid_id=grid.id,
            device_id=member.id,
            top_left_x_cm=0.0,
            top_left_y_cm=0.0,
            width_cm=40.0,
            height_cm=40.0,
        )
        grid_id = grid.id
        await _add(async_engine, grid, member, placement)

        await _rotate_single_grid(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt), grid_id)

        # Gate fires before any rendering or pushing happens.
        mock_s3_service.upload_image.assert_not_called()
        mock_mqtt.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_grid_resumes_once_member_error_is_stale(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        grid = Grid(id=uuid4(), name="wall", width_cm=80.0, height_cm=40.0, scheduled_next_at=PAST)
        member = _due_device(seed_profile, "grid-member", last_refresh_ok=False, last_error_at=STALE_ERROR_AT)
        placement = GridDevice(
            grid_id=grid.id,
            device_id=member.id,
            top_left_x_cm=0.0,
            top_left_y_cm=0.0,
            width_cm=40.0,
            height_cm=40.0,
        )
        grid_id = grid.id
        await _add(async_engine, grid, member, placement)

        # The stale member must no longer pause the grid: the tick has to get
        # past the health gate and reach image selection (which the paused
        # case never does).
        with patch(
            "inky_image_display_api.services.rotation.grid_service.get_next_grid_image",
            new=AsyncMock(return_value=None),
        ) as pick:
            await _rotate_single_grid(_app(async_engine, mock_settings, mock_s3_service, mock_mqtt), grid_id)

        pick.assert_awaited_once()


class TestGenAiGate:
    @pytest.mark.asyncio
    async def test_errored_device_is_not_a_genai_target(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        errored = _due_device(seed_profile, "errored", last_refresh_ok=False)
        await _add(async_engine, errored)
        await _seed_default_preset(async_engine)
        mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
        mock_settings.default_display_duration = 3600
        mock_mqtt.is_connected = MagicMock(return_value=True)
        tasks = MagicMock()

        with (
            patch(
                "inky_image_display_api.services.generation_service.generate_image_bytes",
                new=AsyncMock(return_value=b"raw"),
            ),
            patch(
                "inky_image_display_api.services.generation_service.ImageProcessor.process_for_display",
                return_value=b"processed",
            ),
        ):
            await generate_and_publish(
                async_engine,
                mock_settings,
                mock_s3_service,
                mock_mqtt,
                task_id=uuid4(),
                subject="a cat",
                target_device_profile_id=seed_profile.id,
                preset_id=None,
                orientation="landscape",
                push_immediately=True,
                tasks=tasks,
            )

        # Image is still persisted, but the errored device is not pushed to.
        mock_mqtt.send_command.assert_not_awaited()
        completion = tasks.mark_completed.call_args.kwargs.get("detail", "")
        assert "no matching online device" in completion

    @pytest.mark.asyncio
    async def test_stale_error_device_becomes_genai_target_again(
        self, async_engine, mock_settings, mock_s3_service, mock_mqtt, seed_profile
    ) -> None:
        stale = _due_device(seed_profile, "stale", last_refresh_ok=False, last_error_at=STALE_ERROR_AT)
        await _add(async_engine, stale)
        await _seed_default_preset(async_engine)
        mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
        mock_settings.default_display_duration = 3600
        mock_mqtt.is_connected = MagicMock(return_value=True)
        tasks = MagicMock()

        with (
            patch(
                "inky_image_display_api.services.generation_service.generate_image_bytes",
                new=AsyncMock(return_value=b"raw"),
            ),
            patch(
                "inky_image_display_api.services.generation_service.ImageProcessor.process_for_display",
                return_value=b"processed",
            ),
        ):
            await generate_and_publish(
                async_engine,
                mock_settings,
                mock_s3_service,
                mock_mqtt,
                task_id=uuid4(),
                subject="a cat",
                target_device_profile_id=seed_profile.id,
                preset_id=None,
                orientation="landscape",
                push_immediately=True,
                tasks=tasks,
            )

        pushed = {call.args[0] for call in mock_mqtt.send_command.call_args_list}
        assert pushed == {"stale"}
