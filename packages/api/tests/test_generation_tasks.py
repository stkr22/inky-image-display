"""Tests for the persistent generation task store and its REST endpoint."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.routes import genai_generate
from inky_image_display_api.services.generation_tasks import GenerationTaskStore
from inky_image_display_shared.models import GenerationTask
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, update

_EPOCH = datetime(2020, 1, 1)


async def _create_at(engine: AsyncEngine, store: GenerationTaskStore, task_id: UUID, subject: str, minute: int) -> None:
    """Create a task, then pin its ``created_at`` so ordering never depends on clock resolution.

    Backdated to a fixed epoch: each new row is briefly "now" (newest), which
    is also what it is in the sequence, so the store's pruning sees the
    same order it would in production.
    """
    await store.create(task_id, subject)
    async with engine.begin() as conn:
        await conn.execute(
            update(GenerationTask)
            .where(col(GenerationTask.task_id) == task_id)
            .values(created_at=_EPOCH + timedelta(minutes=minute))
        )


class TestGenerationTaskStore:
    """Unit tests for the bounded DB-backed store."""

    async def test_create_and_list_newest_first(self, async_engine: AsyncEngine) -> None:
        store = GenerationTaskStore(async_engine)
        first_id, second_id = uuid4(), uuid4()
        await _create_at(async_engine, store, first_id, "a fox", 0)
        await _create_at(async_engine, store, second_id, "a heron", 1)
        recent = await store.list_recent()
        assert [t.task_id for t in recent] == [second_id, first_id]
        assert recent[0].status == "queued"

    async def test_lifecycle_transitions(self, async_engine: AsyncEngine) -> None:
        store = GenerationTaskStore(async_engine)
        task_id = uuid4()
        await store.create(task_id, "a fox")
        await store.mark_running(task_id)
        assert (await store.list_recent())[0].status == "running"

        image_id = uuid4()
        await store.mark_completed(task_id, image_id=image_id, detail="Pushed to test-display")
        task = (await store.list_recent())[0]
        assert task.status == "completed"
        assert task.image_id == image_id
        assert task.finished_at is not None
        assert task.detail == "Pushed to test-display"

    async def test_mark_failed_records_error(self, async_engine: AsyncEngine) -> None:
        store = GenerationTaskStore(async_engine)
        task_id = uuid4()
        await store.create(task_id, "a fox")
        await store.mark_failed(task_id, "Gemini exploded")
        task = (await store.list_recent())[0]
        assert task.status == "failed"
        assert task.error == "Gemini exploded"
        assert task.finished_at is not None

    async def test_pruning_keeps_history_bounded(self, async_engine: AsyncEngine) -> None:
        store = GenerationTaskStore(async_engine, max_tasks=3)
        ids = [uuid4() for _ in range(5)]
        for minute, task_id in enumerate(ids):
            await _create_at(async_engine, store, task_id, "subject", minute)
        recent = await store.list_recent()
        assert [t.task_id for t in recent] == ids[:1:-1]
        # Oldest two were pruned; mutation on them is a silent no-op.
        await store.mark_failed(ids[0], "late failure")
        assert all(t.task_id != ids[0] for t in await store.list_recent())

    async def test_history_survives_new_store_instance(self, async_engine: AsyncEngine) -> None:
        """The point of persistence: a new store (= API restart) still sees history."""
        task_id = uuid4()
        await GenerationTaskStore(async_engine).create(task_id, "a fox")
        recent = await GenerationTaskStore(async_engine).list_recent()
        assert [t.task_id for t in recent] == [task_id]


@pytest.fixture
def tasks_app(async_engine: AsyncEngine) -> FastAPI:
    """Minimal app exposing only the genai routes with a DB-backed store."""
    app = FastAPI()
    app.state.engine = async_engine
    app.state.generation_tasks = GenerationTaskStore(async_engine)
    app.include_router(genai_generate.router)
    return app


class TestGenerationTasksEndpoint:
    """GET /api/genai/tasks reads the store."""

    async def test_returns_serialized_tasks(self, tasks_app: FastAPI) -> None:
        store: GenerationTaskStore = tasks_app.state.generation_tasks
        task_id = uuid4()
        await store.create(task_id, "a fox in snow")
        await store.mark_running(task_id)

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

    async def test_limit_caps_results(self, tasks_app: FastAPI) -> None:
        store: GenerationTaskStore = tasks_app.state.generation_tasks
        for index in range(5):
            await _create_at(tasks_app.state.engine, store, uuid4(), f"subject {index}", index)
        with TestClient(tasks_app) as client:
            response = client.get("/api/genai/tasks", params={"limit": 2})
        assert len(response.json()) == 2
        assert response.json()[0]["subject"] == "subject 4"
