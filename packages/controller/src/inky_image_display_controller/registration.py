"""HTTP registration helper.

Replaces the old WebSocket-handshake registration. The controller calls
this once on startup to upsert its device record and obtain S3 reader
credentials before opening the MQTT transport.
"""

import logging

import httpx
from inky_image_display_shared.schemas import DeviceRegistration, RegistrationResponse

from inky_image_display_controller.config import APIConfig

logger = logging.getLogger(__name__)


async def register(api_config: APIConfig, registration: DeviceRegistration) -> RegistrationResponse:
    """POST the registration payload and return the parsed response."""
    url = f"{api_config.url.rstrip('/')}/api/devices/register"
    headers = {"Content-Type": "application/json"}
    if api_config.token is not None:
        headers["x-api-key"] = api_config.token.get_secret_value()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            url,
            content=registration.model_dump_json(),
            headers=headers,
        )
        resp.raise_for_status()
        result = RegistrationResponse.model_validate_json(resp.text)
        logger.info("Registered device %s (status=%s)", registration.device_id, result.status)
        return result
