"""Serialisation contracts of the shared API/device schemas."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import pytest
from inky_image_display_shared.schemas import RegistrationResponse
from inky_image_display_shared.schemas.responses import (
    CalibreSyncJobResponse,
    GeminiSyncJobResponse,
    PromptBlockResponse,
    PromptPresetResponse,
    SyncJobResponse,
)
from pydantic import BaseModel, PlainSerializer

_NAIVE = datetime(2026, 5, 17, 14, 0, 0)  # stored columns are naive UTC


def test_prompt_block_timestamps_serialise_with_utc_offset() -> None:
    block = PromptBlockResponse(id=uuid4(), kind="style", name="n", text="t", created_at=_NAIVE, updated_at=_NAIVE)
    payload = json.loads(block.model_dump_json())
    # Without the offset browsers parse the string as local time.
    assert payload["created_at"] == "2026-05-17T14:00:00+00:00"
    assert payload["updated_at"] == "2026-05-17T14:00:00+00:00"


@pytest.mark.parametrize(
    "model",
    [SyncJobResponse, PromptPresetResponse, GeminiSyncJobResponse, CalibreSyncJobResponse, PromptBlockResponse],
)
def test_every_timestamp_field_is_utc_aware(model: type[BaseModel]) -> None:
    # Guards against a new bare ``datetime`` field slipping back in: every
    # datetime on these responses must use the offset-emitting UtcDatetime.
    checked = 0
    for name, field in model.model_fields.items():
        if "datetime" not in repr(field.annotation):
            continue
        checked += 1
        # A bare ``UtcDatetime`` has its serializer lifted into ``metadata``;
        # ``UtcDatetime | None`` keeps it inside the union annotation.
        has_serializer = any(isinstance(m, PlainSerializer) for m in field.metadata)
        assert has_serializer or "PlainSerializer" in repr(field.annotation), name
    assert checked >= 2


def _registration() -> RegistrationResponse:
    return RegistrationResponse(
        status="registered",
        s3_endpoint="s3:9000",
        s3_bucket="b",
        s3_access_key="ak",
        s3_secret_key="s3-secret",
        mqtt_host="broker",
        mqtt_password="mqtt-secret",
    )


def test_registration_secrets_reach_the_wire_in_clear() -> None:
    # The device needs the real credentials; masking them in JSON would break
    # every controller's S3 and MQTT login.
    payload = json.loads(_registration().model_dump_json())
    assert payload["s3_secret_key"] == "s3-secret"
    assert payload["mqtt_password"] == "mqtt-secret"
    assert _registration().model_dump(mode="json")["s3_secret_key"] == "s3-secret"


def test_registration_secrets_round_trip_through_json() -> None:
    parsed = RegistrationResponse.model_validate_json(_registration().model_dump_json())
    assert parsed.s3_secret_key.get_secret_value() == "s3-secret"
    assert parsed.mqtt_password is not None
    assert parsed.mqtt_password.get_secret_value() == "mqtt-secret"


def test_registration_secrets_are_masked_in_repr_and_logs() -> None:
    response = _registration()
    text = repr(response) + str(response) + str(response.model_dump())
    assert "s3-secret" not in text
    assert "mqtt-secret" not in text


def test_registration_without_mqtt_password_serialises_null() -> None:
    response = RegistrationResponse(
        status="registered", s3_endpoint="s3", s3_bucket="b", s3_access_key="ak", s3_secret_key="sk", mqtt_host="h"
    )
    assert json.loads(response.model_dump_json())["mqtt_password"] is None
