"""Tests for the generation task registry and its REST endpoint."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.routes import genai_generate
from inky_image_display_api.services.generation_tasks import GenerationTaskRegistry


class TestGenerationTaskRegistry:
    """Unit tests for the bounded in-memory registry."""

    def test_create_and_list_newest_first(self) -> None:
        registry = GenerationTaskRegistry()
        first = registry.create(uuid4(), "a fox")
        second = registry.create(uuid4(), "a heron")
        recent = registry.list_recent()
        assert [t.task_id for t in recent] == [second.task_id, first.task_id]
        assert recent[0].status == "queued"

    def test_lifecycle_transitions(self) -> None:
        registry = GenerationTaskRegistry()
        task_id = uuid4()
        registry.create(task_id, "a fox")
        registry.mark_running(task_id)
        assert registry.list_recent()[0].status == "running"

        image_id = uuid4()
        registry.mark_completed(task_id, image_id=image_id, detail="Pushed to test-display")
        task = registry.list_recent()[0]
        assert task.status == "completed"
        assert task.image_id == image_id
        assert task.finished_at is not None
        assert task.detail == "Pushed to test-display"

    def test_mark_failed_records_error(self) -> None:
        registry = GenerationTaskRegistry()
        task_id = uuid4()
        registry.create(task_id, "a fox")
        registry.mark_failed(task_id, "Gemini exploded")
        task = registry.list_recent()[0]
        assert task.status == "failed"
        assert task.error == "Gemini exploded"
        assert task.finished_at is not None

    def test_eviction_keeps_registry_bounded(self) -> None:
        registry = GenerationTaskRegistry(max_tasks=3)
        ids = [uuid4() for _ in range(5)]
        for task_id in ids:
            registry.create(task_id, "subject")
        recent = registry.list_recent()
        assert len(recent) == 3
        # Oldest two were evicted; mutation on them is a silent no-op.
        registry.mark_failed(ids[0], "late failure")
        assert all(t.task_id != ids[0] for t in registry.list_recent())


@pytest.fixture
def tasks_app() -> FastAPI:
    """Minimal app exposing only the genai routes with an empty registry."""
    app = FastAPI()
    app.state.generation_tasks = GenerationTaskRegistry()
    app.include_router(genai_generate.router)
    return app


class TestGenerationTasksEndpoint:
    """GET /api/genai/tasks reads the registry."""

    def test_returns_serialized_tasks(self, tasks_app: FastAPI) -> None:
        registry: GenerationTaskRegistry = tasks_app.state.generation_tasks
        task_id = uuid4()
        registry.create(task_id, "a fox in snow")
        registry.mark_running(task_id)

        with TestClient(tasks_app) as client:
            response = client.get("/api/genai/tasks")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["task_id"] == str(task_id)
        assert body[0]["subject"] == "a fox in snow"
        assert body[0]["status"] == "running"
        assert body[0]["image_id"] is None
        # Aware ISO timestamp at the boundary.
        assert "+00:00" in body[0]["created_at"]

    def test_limit_caps_results(self, tasks_app: FastAPI) -> None:
        registry: GenerationTaskRegistry = tasks_app.state.generation_tasks
        for index in range(5):
            registry.create(uuid4(), f"subject {index}")
        with TestClient(tasks_app) as client:
            response = client.get("/api/genai/tasks", params={"limit": 2})
        assert len(response.json()) == 2
        assert response.json()[0]["subject"] == "subject 4"
