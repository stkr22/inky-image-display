"""Tests for the DisplayAPIClient machine-token header."""

import logging

from inky_image_display_sync.api_client import DisplayAPIClient
from inky_image_display_sync.immich.config import APIClientConfig
from pydantic import HttpUrl, SecretStr


def test_token_is_sent_as_x_api_key_header():
    config = APIClientConfig(base_url=HttpUrl("http://api.test"), token=SecretStr("sync-key"))
    client = DisplayAPIClient(config=config, logger=logging.getLogger(__name__))
    assert client._client.headers["x-api-key"] == "sync-key"


def test_no_token_sends_no_header():
    config = APIClientConfig(base_url=HttpUrl("http://api.test"))
    client = DisplayAPIClient(config=config, logger=logging.getLogger(__name__))
    assert "x-api-key" not in client._client.headers
