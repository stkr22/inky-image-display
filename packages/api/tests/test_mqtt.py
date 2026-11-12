"""Tests for the API-side MQTT service."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aiomqtt
import pytest
from inky_image_display_api import mqtt as mqtt_module
from inky_image_display_api.config import Settings
from inky_image_display_api.mqtt import MQTTService, _record_ack
from inky_image_display_api.services.device_registry import upsert_device
from inky_image_display_shared.models import Device
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DeviceStatus,
    DisplayCommand,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


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
        # A successful ack records healthy refresh state.
        assert refreshed.last_refresh_ok is True
        assert refreshed.last_error is None
        assert refreshed.last_error_at is None


async def _send_ack(service: MQTTService, device_id: str, *, success: bool, error: str | None) -> None:
    payload = (
        DeviceAcknowledge(device_id=device_id, image_id=None, successful_display_change=success, error=error)
        .model_dump_json()
        .encode()
    )
    await service._dispatch(_msg(f"inky/devices/{device_id}/ack", payload))


@pytest.mark.asyncio
async def test_failed_ack_persists_error_then_success_clears_it(
    settings: Settings, async_engine: AsyncEngine, seeded_device: Device
):
    service = MQTTService(settings, async_engine)

    # A failed refresh ack stores the error and keeps the device online —
    # this is the stuck-display signal the UI surfaces.
    await _send_ack(service, seeded_device.device_id, success=False, error="BUSY never cleared")
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.is_online is True
        assert refreshed.last_refresh_ok is False
        assert refreshed.last_error == "BUSY never cleared"
        assert refreshed.last_error_at is not None

    # A subsequent success clears the error state.
    await _send_ack(service, seeded_device.device_id, success=True, error=None)
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.last_refresh_ok is True
        assert refreshed.last_error is None
        assert refreshed.last_error_at is None


@pytest.mark.asyncio
async def test_refresh_health_transitions_notify_once(
    settings: Settings, async_engine: AsyncEngine, seeded_device: Device, monkeypatch: pytest.MonkeyPatch
):
    """Only entering or leaving the failed state pushes; repeats stay quiet."""
    sent: list[str] = []
    monkeypatch.setattr(
        "inky_image_display_api.mqtt.notify_in_background",
        lambda _settings, title, _message: sent.append(title),
    )
    settings.notify_url = "https://ntfy.example/inky"

    device_id = seeded_device.device_id
    for success, error in [(False, "stuck"), (False, "stuck"), (True, None), (True, None)]:
        await _record_ack(async_engine, device_id, success=success, error=error, settings=settings)

    assert len(sent) == 2
    assert "refresh failed" in sent[0]
    assert "recovered" in sent[1]


@pytest.mark.asyncio
async def test_reregistration_clears_stale_refresh_error(
    async_engine: AsyncEngine, seeded_device: Device, seed_profile
):
    """Registration happens once per controller start, so a recorded failure
    describes a dead controller whose in-memory retry is gone — re-registering
    must reset refresh health or the device would never re-enter rotation."""
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        device = result.one()
        device.last_refresh_ok = False
        device.last_error = "BUSY never cleared"
        device.last_error_at = datetime(2026, 7, 10, 12, 0, 0)
        session.add(device)
        await session.commit()

    registration = DeviceRegistration(
        device_id=seeded_device.device_id,
        device_profile_key=seed_profile.key,
        orientation="landscape",
        room=None,
    )
    outcome = await upsert_device(async_engine, seeded_device.device_id, registration)

    assert outcome == "updated"
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == seeded_device.device_id))
        refreshed = result.one()
        assert refreshed.last_refresh_ok is None
        assert refreshed.last_error is None
        assert refreshed.last_error_at is None


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


class _FlakyBroker:
    """Stands in for ``aiomqtt.Client``: scripted outcome per connection attempt.

    Each script entry is either an exception raised on connect, or
    ``"connect-then-drop"`` — connect, then lose the connection while
    reading messages.
    """

    def __init__(self, script: list[BaseException | str]) -> None:
        self.script = script
        self.subscriptions: list[str] = []

    def __call__(self, **_kwargs: object) -> "_FlakyBroker":
        return self

    async def __aenter__(self) -> "_FlakyBroker":
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def subscribe(self, topic: str, qos: int) -> None:
        self.subscriptions.append(topic)

    @property
    def messages(self) -> "_FlakyBroker":
        return self

    def __aiter__(self) -> "_FlakyBroker":
        return self

    async def __anext__(self) -> MagicMock:
        raise aiomqtt.MqttError("connection dropped")


@pytest.mark.asyncio
async def test_run_reconnects_with_backoff_and_resubscribes(
    settings: Settings, async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    broker = _FlakyBroker(
        [
            aiomqtt.MqttError("refused"),
            aiomqtt.MqttError("refused"),
            "connect-then-drop",
            asyncio.CancelledError(),  # ends the otherwise endless loop
        ]
    )
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(mqtt_module.aiomqtt, "Client", broker)
    monkeypatch.setattr(mqtt_module.asyncio, "sleep", fake_sleep)
    service = MQTTService(settings, async_engine)
    service._online.add("stale-device")

    with pytest.raises(asyncio.CancelledError):
        await service.run()

    # Doubling while the broker refuses; reset after a successful connect.
    assert sleeps == [5, 10, 5]
    assert broker.subscriptions == [
        "inky/devices/+/status",
        "inky/devices/+/ack",
        mqtt_module.WORKER_STATUS_TOPIC,
    ]
    # A lost connection forgets presence; retained statuses re-announce it.
    assert not service.is_connected("stale-device")
