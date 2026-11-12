"""Solo rotation picks: which images are eligible and how long each one holds.

The picker chooses randomly within a least-recently-shown window, so these
tests capture the candidate list handed to ``random.choice`` instead of
sampling the pick repeatedly — the eligible set is the behaviour that
matters, and asserting on it is deterministic.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from inky_image_display_api.services import image_service
from inky_image_display_api.services.image_service import get_next_image_for_device, update_display_state
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .conftest import add_images

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings
    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
def candidates(monkeypatch: pytest.MonkeyPatch) -> list[list[Image]]:
    """Record each candidate window and always pick its first entry."""
    seen: list[list[Image]] = []

    def first(pool: list[Image]) -> Image:
        seen.append(pool)
        return pool[0]

    monkeypatch.setattr(image_service.random, "choice", first)
    return seen


class TestSelection:
    async def test_excluded_images_never_selected(
        self, async_engine: AsyncEngine, seed_device: Device, candidates: list[list[Image]]
    ) -> None:
        images = await add_images(async_engine, 3)
        async with AsyncSession(async_engine) as session:
            for image in images[:2]:
                row = (await session.exec(select(Image).where(col(Image.id) == image.id))).one()
                row.excluded_from_rotation = True
                session.add(row)
            await session.commit()

        async with AsyncSession(async_engine) as session:
            picked = await get_next_image_for_device(session, seed_device)
        assert picked is not None
        assert [img.id for img in candidates[0]] == [images[2].id]

    async def test_pick_is_among_least_recently_shown_window(
        self, async_engine: AsyncEngine, seed_device: Device, candidates: list[list[Image]]
    ) -> None:
        images = await add_images(async_engine, 8)
        async with AsyncSession(async_engine) as session:
            await get_next_image_for_device(session, seed_device)
        # The five least recently shown, oldest first; the three newest never qualify.
        assert [img.id for img in candidates[0]] == [img.id for img in images[:5]]

    async def test_duration_override_beats_device_interval(
        self, async_engine: AsyncEngine, seed_device: Device, settings: Settings
    ) -> None:
        async with AsyncSession(async_engine) as session:
            image = Image(
                source_name="manual",
                storage_path="manual/hold.jpg",
                original_width=1600,
                original_height=1200,
                display_duration_seconds=7200,
            )
            device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
            session.add(image)
            before = utcnow()
            await update_display_state(session, device, image, settings)

        # Re-read: update_display_state commits, which expires the instance.
        async with AsyncSession(async_engine) as session:
            device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
            held_until = device.scheduled_next_at
        assert held_until is not None
        assert timedelta(seconds=7100) < held_until - before < timedelta(seconds=7300)
