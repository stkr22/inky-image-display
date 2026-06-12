"""Tests for the Immich browse proxy endpoints."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.routes import immich_browse
from pydantic import SecretStr


@pytest.fixture
def immich_settings() -> MagicMock:
    settings = MagicMock()
    settings.immich_base_url = "http://immich.test"
    settings.immich_api_key = SecretStr("key")
    settings.immich_timeout_seconds = 5.0
    return settings


@pytest.fixture
def immich_app(immich_settings: MagicMock) -> FastAPI:
    app = FastAPI()
    app.state.settings = immich_settings
    app.include_router(immich_browse.router)
    return app


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, payload_by_path: dict[str, Any]) -> None:
    async def fake_fetch(settings: Any, path: str, params: dict[str, Any] | None = None) -> Any:
        del settings, params
        return payload_by_path[path]

    monkeypatch.setattr(immich_browse, "_fetch_json", fake_fetch)


class TestImmichBrowse:
    def test_unconfigured_returns_503(self, immich_app: FastAPI, immich_settings: MagicMock) -> None:
        immich_settings.immich_base_url = None
        immich_settings.immich_api_key = None
        with TestClient(immich_app) as client:
            response = client.get("/api/immich/albums")
        assert response.status_code == 503

    def test_albums_mapped_and_sorted(self, immich_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_fetch(
            monkeypatch,
            {
                "/api/albums": [
                    {"id": "b", "albumName": "Zoo trip"},
                    {"id": "a", "albumName": "Alps 2025"},
                ]
            },
        )
        with TestClient(immich_app) as client:
            response = client.get("/api/immich/albums")
        assert response.status_code == 200
        assert response.json() == [
            {"id": "a", "name": "Alps 2025"},
            {"id": "b", "name": "Zoo trip"},
        ]

    def test_people_skips_unnamed_faces(self, immich_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_fetch(
            monkeypatch,
            {
                "/api/people": {
                    "people": [
                        {"id": "p1", "name": "Ada"},
                        {"id": "p2", "name": ""},
                    ],
                    "total": 2,
                }
            },
        )
        with TestClient(immich_app) as client:
            response = client.get("/api/immich/people")
        assert response.json() == [{"id": "p1", "name": "Ada"}]

    def test_tags_prefer_hierarchical_value(self, immich_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_fetch(
            monkeypatch,
            {
                "/api/tags": [
                    {"id": "t1", "name": "beach", "value": "travel/beach"},
                    {"id": "t2", "name": "dogs", "value": None},
                ]
            },
        )
        with TestClient(immich_app) as client:
            response = client.get("/api/immich/tags")
        assert response.json() == [
            {"id": "t2", "name": "dogs"},
            {"id": "t1", "name": "travel/beach"},
        ]
