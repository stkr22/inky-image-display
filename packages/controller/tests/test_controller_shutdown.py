"""Tests for graceful shutdown of the controller's run loop.

SIGTERM only sets the shutdown event; ``run()`` must then tear down the
long-running MQTT task, publish ``offline`` and release resources. A shutdown
that leaves ``MQTTClient.run()`` alive hangs the service until systemd kills it.
"""

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from inky_image_display_controller import controller as controller_module
from inky_image_display_controller.config import Settings
from inky_image_display_controller.controller import DisplayController
from inky_image_display_shared.schemas import RegistrationResponse


class _ForeverMQTT:
    """MQTT client stand-in whose ``run()`` never returns on its own."""

    instances: ClassVar[list["_ForeverMQTT"]] = []
    started: ClassVar[asyncio.Event]

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.cancelled = False
        self.disconnect = AsyncMock()
        _ForeverMQTT.instances.append(self)

    async def run(self) -> None:
        _ForeverMQTT.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _registration() -> RegistrationResponse:
    return RegistrationResponse(
        status="registered",
        s3_endpoint="s3.test:9000",
        s3_bucket="bucket",
        s3_access_key="ak",
        s3_secret_key="sk",
        mqtt_host="broker.test",
        mqtt_password="pw",
    )


def _controller() -> DisplayController:
    settings = Settings()
    settings.display.mock = True
    controller = DisplayController(settings)
    controller._s3 = MagicMock()
    return controller


@pytest.fixture(autouse=True)
def _reset_instances() -> None:
    _ForeverMQTT.instances.clear()
    _ForeverMQTT.started = asyncio.Event()


@pytest.mark.asyncio
async def test_shutdown_cancels_mqtt_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller_module, "register", AsyncMock(return_value=_registration()))
    monkeypatch.setattr(controller_module, "MQTTClient", _ForeverMQTT)
    controller = _controller()

    run_task = asyncio.create_task(controller.run())
    await _ForeverMQTT.started.wait()
    mqtt = _ForeverMQTT.instances[0]

    await controller.shutdown()
    await asyncio.wait_for(run_task, timeout=2.0)  # returns instead of hanging

    assert mqtt.cancelled
    # Offline is announced (by the monitor, while still connected) and the
    # cleanup path runs; disconnect is idempotent so a second call is harmless.
    assert mqtt.disconnect.await_count >= 1
    controller._s3.close.assert_called_once()  # ty: ignore[missing-attribute]


@pytest.mark.asyncio
async def test_registration_credentials_are_unwrapped_for_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller_module, "MQTTClient", _ForeverMQTT)
    controller = _controller()

    controller._apply_registration_response(_registration())

    assert controller._s3.configure.call_args.kwargs["secret_key"] == "sk"  # ty: ignore[missing-attribute]
    assert _ForeverMQTT.instances[0].kwargs["password"] == "pw"


@pytest.mark.asyncio
async def test_shutdown_during_registration_returns_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = asyncio.Event()

    async def failing_register(*_args: object) -> RegistrationResponse:
        attempts.set()
        raise ConnectionError("api down")

    monkeypatch.setattr(controller_module, "register", failing_register)
    controller = _controller()

    run_task = asyncio.create_task(controller.run())
    await attempts.wait()
    await controller.shutdown()
    # Previously a bare CancelledError escaped run() here.
    await asyncio.wait_for(run_task, timeout=2.0)

    controller._s3.close.assert_called_once()  # ty: ignore[missing-attribute]
