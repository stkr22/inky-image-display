"""Tests for the API-side MQTT service."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from inky_image_display_api.config import Settings
from inky_image_display_api.mqtt import MQTTService
from inky_image_display_shared.models import Device
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceStatus,
    DisplayCommand,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


def _make_settings() -> Settings:
    """Build a fully-populated Settings instance with MQTT defaults."""
    return Settings(
        database_path="/tmp/unused.db",
        s3_endpoint="s3.test.local:9000",
        s3_writer_access_key="w",
        s3_writer_secret_key="w",
        s3_reader_access_key="r",
        s3_reader_secret_key="r",
        mqtt_host="broker.test",
        device_mqtt_host="broker.public.test",
    )


@pytest.fixture
def settings() -> Settings:
    return _make_settings()


@pytest.fixture
async def seeded_device(async_engine: AsyncEngine, seed_profile) -> Device:
    """A persisted device whose ``is_online`` flag we can flip in tests."""
    device = Device(
        id=uuid4(),
        device_id="dev-1",
        device_profile_id=seed_profile.id,
        is_online=False,
        last_seen=datetime(2000, 1, 1),
    )
    async with AsyncSession(async_engine) as session:
        session.add(device)
        await session.commit()
        await session.refresh(device)
    return device


def _msg(topic: str, payload: bytes) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload
    return msg


@pytest.mark.asyncio
async def test_status_online_marks_device_online(settings: Settings, async_engine: AsyncEngine, seeded_device: Device):
    service = MQTTService(settings, async_engine)
    payload = DeviceStatus(status="online").model_dump_json().encode()
    await service._dispatch(_msg(f"inky/devices/{seeded_device.device_id}/status", payload))

    assert service.is_connected(seeded_device.device_id)
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.is_online is True


@pytest.mark.asyncio
async def test_status_offline_marks_device_offline(
    settings: Settings, async_engine: AsyncEngine, seeded_device: Device
):
    service = MQTTService(settings, async_engine)
    # Device first comes online.
    online = DeviceStatus(status="online").model_dump_json().encode()
    await service._dispatch(_msg(f"inky/devices/{seeded_device.device_id}/status", online))

    offline = DeviceStatus(status="offline").model_dump_json().encode()
    await service._dispatch(_msg(f"inky/devices/{seeded_device.device_id}/status", offline))

    assert not service.is_connected(seeded_device.device_id)
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.is_online is False


@pytest.mark.asyncio
async def test_ack_keeps_device_online_and_touches_last_seen(
    settings: Settings, async_engine: AsyncEngine, seeded_device: Device
):
    service = MQTTService(settings, async_engine)
    ack = (
        DeviceAcknowledge(
            device_id=seeded_device.device_id,
            image_id=None,
            successful_display_change=True,
            error=None,
        )
        .model_dump_json()
        .encode()
    )
    await service._dispatch(_msg(f"inky/devices/{seeded_device.device_id}/ack", ack))

    assert service.is_connected(seeded_device.device_id)
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.is_online is True
        # last_seen should have been bumped past the seeded epoch value.
        assert refreshed.last_seen.year >= 2024


@pytest.mark.asyncio
async def test_send_command_publishes_to_correct_topic(settings: Settings, async_engine: AsyncEngine):
    service = MQTTService(settings, async_engine)
    fake_client = MagicMock()
    fake_client.publish = AsyncMock()
    service._client = fake_client
    service._online.add("dev-1")

    cmd = DisplayCommand(action="clear")
    await service.send_command("dev-1", cmd)

    fake_client.publish.assert_awaited_once()
    topic, payload = fake_client.publish.call_args.args
    assert topic == "inky/devices/dev-1/cmd"
    assert payload == cmd.model_dump_json()
    assert fake_client.publish.call_args.kwargs["qos"] == 1


@pytest.mark.asyncio
async def test_send_command_unknown_device_raises(settings: Settings, async_engine: AsyncEngine):
    service = MQTTService(settings, async_engine)
    service._client = MagicMock()
    with pytest.raises(KeyError):
        await service.send_command("dev-unknown", DisplayCommand(action="clear"))
