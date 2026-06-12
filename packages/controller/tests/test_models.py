"""Wire-contract tests for the MQTT/HTTP message schemas the controller consumes.

Pydantic's own validation behaviour is not re-tested here; these guard the
two payload shapes the controller exchanges with the API in production.
"""

from inky_image_display_shared.schemas import DeviceRegistration, DisplayCommand


def test_registration_round_trips_with_defaults() -> None:
    """The registration payload sent to the API: defaults must survive JSON."""
    reg = DeviceRegistration(
        device_id="test-device",
        device_profile_key="inky_impression_13_spectra6",
        room="Kitchen",
    )
    parsed = DeviceRegistration.model_validate_json(reg.model_dump_json())
    assert parsed.device_id == "test-device"
    assert parsed.orientation == "landscape"  # default the API relies on
    assert parsed.room == "Kitchen"


def test_display_command_parses_from_mqtt_payload() -> None:
    """Commands arrive as raw JSON on the MQTT topic; clear omits image fields."""
    cmd = DisplayCommand.model_validate_json(
        '{"action": "display", "image_path": "photos/sunset.jpg", "image_id": "img-123"}'
    )
    assert cmd.action == "display"
    assert cmd.image_path == "photos/sunset.jpg"

    clear = DisplayCommand.model_validate_json('{"action": "clear"}')
    assert clear.image_path is None
    assert clear.image_id is None
