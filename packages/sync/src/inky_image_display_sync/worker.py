"""Long-running sync worker driven by MQTT wakes.

Replaces the per-job-family Kubernetes CronJobs. The API decides
due-ness (cron schedules on the job rows) and rings the wake topic; this
process then claims due jobs over HTTP exactly like the one-shot CLI
commands do. The doorbell carries no work on purpose: the job rows stay
the source of truth, so a duplicate wake claims nothing twice and a
missed wake is covered by the startup claim and the slow safety poll.

Presence is announced on a retained status topic with a Last-Will
(mirroring the device controllers), so the API can show worker liveness
in the UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Literal

import aiomqtt
from inky_image_display_shared.schemas import DeviceStatus
from pydantic import SecretStr  # noqa: TC002 — pydantic-settings resolves at runtime
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("inky_image_display_sync")

# Topic contract shared with the API's MQTTService.
WAKE_TOPIC = "inky/workers/sync/wake"
STATUS_TOPIC = "inky/workers/sync/status"

_INITIAL_RECONNECT_INTERVAL = 5
_MAX_RECONNECT_INTERVAL = 60


class WorkerConfig(BaseSettings):
    """Worker settings from WORKER_* environment variables.

    ``mqtt_host`` ``None`` runs without a broker: cycles then fire only on
    the safety poll, which degrades to the old CronJob cadence instead of
    breaking. The enable flags mirror the chart's per-family opt-ins so an
    Immich-only deployment never needs a Gemini key.
    """

    model_config = SettingsConfigDict(env_prefix="WORKER_")

    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_transport: Literal["tcp", "websockets"] = "tcp"
    mqtt_websocket_path: str = "/mqtt"
    mqtt_keep_alive: int = 30
    poll_interval_seconds: int = 600
    enable_immich: bool = True
    enable_gemini: bool = False
    enable_display: bool = False


async def run_worker() -> None:
    """Claim-due cycles on wake, on startup, and on the safety poll.

    Cycles run strictly one at a time (the old CronJobs used
    ``concurrencyPolicy: Forbid`` for the same reason); wakes arriving
    mid-cycle coalesce into one follow-up cycle via the event.
    """
    config = WorkerConfig()
    wake = asyncio.Event()
    wake.set()  # Startup cycle: catch anything armed while we were down.

    mqtt_task = asyncio.create_task(_mqtt_loop(config, wake)) if config.mqtt_host else None
    if mqtt_task is None:
        logger.warning("WORKER_MQTT_HOST not set — poll-only mode, every %ds", config.poll_interval_seconds)

    try:
        while True:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(config.poll_interval_seconds):
                    await wake.wait()
            wake.clear()
            await _run_cycle(config)
    finally:
        if mqtt_task is not None:
            mqtt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await mqtt_task


async def _run_cycle(config: WorkerConfig) -> None:
    """One claim-everything pass; a failing family doesn't block the rest."""
    # Imported lazily: main.py imports this module for the CLI command.
    from inky_image_display_sync.main import (  # noqa: PLC0415 — breaks the import cycle with main
        run_display_sync,
        run_gemini_sync,
        run_immich_sync,
    )

    families: list[tuple[str, bool, Callable[[], Awaitable[None]]]] = [
        ("immich", config.enable_immich, lambda: run_immich_sync(dry_run=False)),
        ("gemini", config.enable_gemini, lambda: run_gemini_sync(dry_run=False)),
        ("display", config.enable_display, run_display_sync),
    ]
    for name, enabled, run in families:
        if not enabled:
            continue
        try:
            await run()
        except Exception:
            logger.exception("%s cycle failed; continuing with the next family", name)


async def _mqtt_loop(config: WorkerConfig, wake: asyncio.Event) -> None:
    """Announce presence and turn wake messages into cycle triggers.

    Mirrors the controller's MQTT loop: retained online status, a
    Last-Will ``offline``, and exponential backoff on broker loss. Any
    message on the wake topic sets the event — the payload is
    informational only.
    """
    backoff = _INITIAL_RECONNECT_INTERVAL
    offline = DeviceStatus(status="offline").model_dump_json().encode("utf-8")
    will = aiomqtt.Will(topic=STATUS_TOPIC, payload=offline, qos=1, retain=True)
    password = config.mqtt_password.get_secret_value() if config.mqtt_password is not None else None

    while True:
        try:
            async with aiomqtt.Client(
                hostname=config.mqtt_host or "",
                port=config.mqtt_port,
                username=config.mqtt_username,
                password=password,
                identifier="inky-sync-worker",
                keepalive=config.mqtt_keep_alive,
                tls_params=aiomqtt.TLSParameters() if config.mqtt_tls else None,
                transport=config.mqtt_transport,
                websocket_path=(config.mqtt_websocket_path if config.mqtt_transport == "websockets" else None),
                will=will,
            ) as client:
                backoff = _INITIAL_RECONNECT_INTERVAL
                await client.publish(
                    STATUS_TOPIC,
                    DeviceStatus(status="online").model_dump_json(),
                    qos=1,
                    retain=True,
                )
                await client.subscribe(WAKE_TOPIC, qos=1)
                logger.info("MQTT connected to %s:%s, waiting for wakes", config.mqtt_host, config.mqtt_port)
                # Anything armed while we were disconnected is claimable now.
                wake.set()
                async for _message in client.messages:
                    wake.set()
        except asyncio.CancelledError:
            raise
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT connection lost: %s. Reconnecting in %ds...", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_RECONNECT_INTERVAL)
        except Exception:
            logger.exception("Unexpected MQTT failure; reconnecting in %ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_RECONNECT_INTERVAL)
