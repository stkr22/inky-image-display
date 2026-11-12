"""Tests for the controller's MQTT client: reconnect loop and message handling.

The device must survive broker restarts unattended, so the reconnect loop has
to back off (capped) and fully re-establish its session — resubscribe, re-mark
itself connected — on every successful connect.
"""

import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock

import aiomqtt
import pytest
from inky_image_display_controller import mqtt_client as mqtt_module
from inky_image_display_controller.mqtt_client import MQTTClient
from inky_image_display_shared.schemas import DeviceAcknowledge, DisplayCommand


def _client(on_command: AsyncMock | None = None) -> MQTTClient:
    return MQTTClient(
        device_id="dev-1",
        on_command=on_command or AsyncMock(),
        host="broker.test",
        port=1883,
        username=None,
        password=None,
        tls=False,
        transport="tcp",
        websocket_path="/mqtt",
        keep_alive=30,
    )


class _StopTest(BaseException):
    """Escapes run()'s ``except Exception`` so the infinite loop can end."""


class _FakeAiomqttClient:
    """aiomqtt.Client stand-in: fails the first N connects, then serves messages."""

    connect_failures = 0
    connects = 0
    instances: ClassVar[list["_FakeAiomqttClient"]] = []
    payloads: ClassVar[list[bytes]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.publish = AsyncMock()
        self.subscribe = AsyncMock()
        _FakeAiomqttClient.instances.append(self)

    async def __aenter__(self) -> "_FakeAiomqttClient":
        _FakeAiomqttClient.connects += 1
        if _FakeAiomqttClient.connects <= _FakeAiomqttClient.connect_failures:
            raise aiomqtt.MqttError("connection refused")
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    @property
    def messages(self) -> "_FakeAiomqttClient":
        return self

    def __aiter__(self) -> "_FakeAiomqttClient":
        self._queue = list(_FakeAiomqttClient.payloads)
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._queue:
            return SimpleNamespace(payload=self._queue.pop(0))
        raise _StopTest


@pytest.fixture
def fake_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAiomqttClient]:
    _FakeAiomqttClient.connect_failures = 0
    _FakeAiomqttClient.connects = 0
    _FakeAiomqttClient.instances = []
    _FakeAiomqttClient.payloads = []
    monkeypatch.setattr(mqtt_module.aiomqtt, "Client", _FakeAiomqttClient)
    return _FakeAiomqttClient


@pytest.mark.asyncio
async def test_reconnects_with_backoff_then_subscribes(
    monkeypatch: pytest.MonkeyPatch, fake_aiomqtt: type[_FakeAiomqttClient]
) -> None:
    fake_aiomqtt.connect_failures = 2
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(mqtt_module.asyncio, "sleep", fake_sleep)
    client = _client()

    with pytest.raises(_StopTest):
        await client.run()

    assert fake_aiomqtt.connects == 3
    assert sleeps == [5, 10]  # exponential, starting from the initial interval
    connected = fake_aiomqtt.instances[-1]
    connected.subscribe.assert_awaited_once_with("inky/devices/dev-1/cmd", qos=1)
    online = connected.publish.await_args_list[0]
    assert online.args[0] == "inky/devices/dev-1/status"
    assert '"online"' in online.args[1]
    assert online.kwargs["retain"] is True
    # Wakes any publish_ack() waiting for the connection.
    assert client._connected.is_set()
    # Last-Will announces offline on unexpected disconnects.
    will = fake_aiomqtt.instances[0].kwargs["will"]
    assert isinstance(will, aiomqtt.Will)
    assert will.topic == "inky/devices/dev-1/status"


@pytest.mark.asyncio
async def test_backoff_is_capped(monkeypatch: pytest.MonkeyPatch, fake_aiomqtt: type[_FakeAiomqttClient]) -> None:
    fake_aiomqtt.connect_failures = 6
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(mqtt_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopTest):
        await _client().run()

    assert sleeps == [5, 10, 20, 40, 60, 60]


@pytest.mark.asyncio
async def test_messages_dispatch_and_bad_payloads_are_skipped(fake_aiomqtt: type[_FakeAiomqttClient]) -> None:
    on_command = AsyncMock(side_effect=[RuntimeError("handler boom"), None])
    good = DisplayCommand(action="display", image_path="a.jpg", image_id="img-1").model_dump_json().encode()
    fake_aiomqtt.payloads = [b"not json", good, good]
    client = _client(on_command)

    with pytest.raises(_StopTest):
        await client.run()

    # The malformed payload is dropped, and a handler error on the first good
    # command does not stop the loop from processing the next one.
    assert on_command.await_count == 2
    assert on_command.await_args_list[0].args[0].image_id == "img-1"


@pytest.mark.asyncio
async def test_publish_ack_without_connection_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    real_timeout = asyncio.timeout
    monkeypatch.setattr(mqtt_module.asyncio, "timeout", lambda _delay: real_timeout(0))

    ack = DeviceAcknowledge(device_id="dev-1", image_id="img-1", successful_display_change=True)
    assert await client.publish_ack(ack) is False


@pytest.mark.asyncio
async def test_publish_ack_and_disconnect_when_connected() -> None:
    client = _client()
    broker = AsyncMock()
    client._client = broker
    client._connected.set()

    ack = DeviceAcknowledge(device_id="dev-1", image_id="img-1", successful_display_change=True)
    assert await client.publish_ack(ack) is True
    assert broker.publish.await_args_list[0].args[0] == "inky/devices/dev-1/ack"

    await client.disconnect()
    offline = broker.publish.await_args_list[1]
    assert offline.args[0] == "inky/devices/dev-1/status"
    assert '"offline"' in offline.args[1]
    assert client._client is None
    assert not client._connected.is_set()
