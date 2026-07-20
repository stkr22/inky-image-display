"""Route-level tests for /api/image-groups (panel-spread semantics)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from inky_image_display_shared.models import Image
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncEngine


async def _seed_images(engine: AsyncEngine, count: int) -> list[str]:
    images = [
        Image(source_name="manual", storage_path=f"manual/{uuid4()}.jpg", original_width=1600, original_height=1200)
        for _ in range(count)
    ]
    ids = [str(image.id) for image in images]
    async with AsyncSession(engine) as session:
        for image in images:
            session.add(image)
        await session.commit()
    return ids


@pytest.mark.asyncio
async def test_create_assigns_members_to_panels(client: TestClient, async_engine: AsyncEngine) -> None:
    first, second = await _seed_images(async_engine, 2)
    response = client.post(
        "/api/image-groups",
        json={
            "name": "spread",
            "members": [
                {"image_id": first, "row": 0, "col": 0},
                {"image_id": second, "row": 0, "col": 1},
            ],
        },
    )
    assert response.status_code == 201
    by_id = {image["id"]: image for image in response.json()["images"]}
    assert (by_id[first]["group_slot_row"], by_id[first]["group_slot_col"]) == (0, 0)
    assert (by_id[second]["group_slot_row"], by_id[second]["group_slot_col"]) == (0, 1)


@pytest.mark.asyncio
async def test_update_replaces_slots_and_releases_dropped_members(
    client: TestClient, async_engine: AsyncEngine
) -> None:
    first, second = await _seed_images(async_engine, 2)
    group_id = client.post(
        "/api/image-groups",
        json={"name": "spread", "members": [{"image_id": first, "row": 0, "col": 0}, {"image_id": second}]},
    ).json()["id"]

    response = client.put(
        f"/api/image-groups/{group_id}",
        json={"members": [{"image_id": second, "row": 1, "col": 0}]},
    )
    assert response.status_code == 200
    images = response.json()["images"]
    assert [image["id"] for image in images] == [second]
    assert (images[0]["group_slot_row"], images[0]["group_slot_col"]) == (1, 0)
    async with AsyncSession(async_engine) as session:
        dropped = (await session.exec(select(Image).where(Image.id == UUID(first)))).one()
        assert dropped.group_id is None
        assert dropped.group_slot_row is None


def test_update_rejects_generated_groups(client: TestClient) -> None:
    job = client.post("/api/display-jobs", json={"name": "motd"}).json()
    group = client.post("/api/image-groups", json={"name": "run output", "display_job_id": job["id"]}).json()
    response = client.put(f"/api/image-groups/{group['id']}", json={"name": "renamed"})
    assert response.status_code == 409


def test_member_slot_must_be_complete(client: TestClient) -> None:
    response = client.post(
        "/api/image-groups",
        json={"name": "bad", "members": [{"image_id": str(uuid4()), "row": 0}]},
    )
    assert response.status_code == 422
