"""Deleting an image together with everything derived from it.

Three paths delete images (the image route, group deletion, display-job
pruning); keeping one implementation is what guarantees none of them
leaves book links or derived S3 objects behind. Derived objects are cheap
to recreate but never expire on their own, so without this the bucket only
grows.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from inky_image_display_shared.models import Device, DeviceProfile, Grid, Image, ImageBook
from minio.error import S3Error
from sqlmodel import col, delete, select, update

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.services.s3_service import S3Service

logger = logging.getLogger(__name__)

# Derived-object namespaces. Defined here (and imported by the routes that
# write them) so the writers and this cleanup can't disagree on a key.
THUMB_PREFIX = "thumbs"
ALLOWED_THUMB_WIDTHS = (240, 480, 960)
EINK_PREVIEW_PREFIX = f"{THUMB_PREFIX}/eink"
# Preview saturation is snapped to one decimal, i.e. eleven variants.
EINK_SATURATION_STEPS = range(11)
DERIVED_PREFIX = "derived"
GRID_CROP_PREFIX = "grids"
# Top-level key segments owned by the API's derived objects; uploads must not
# be stored under them or deleting an image could take a real original along.
RESERVED_STORAGE_PREFIXES = frozenset({THUMB_PREFIX, DERIVED_PREFIX, GRID_CROP_PREFIX})


def thumb_key(storage_path: str, width: int) -> str:
    """Cache key of the media proxy's ``?w=`` variant."""
    return f"{THUMB_PREFIX}/w{width}/{storage_path}"


def eink_preview_key(storage_path: str, saturation_step: int) -> str:
    """Cache key of an e-ink preview at ``saturation_step / 10``."""
    return f"{EINK_PREVIEW_PREFIX}/s{saturation_step:02d}/{storage_path}.png"


def derived_fit_key(storage_path: str, width: int, height: int) -> str:
    """Key of a cover-cropped copy sized for one panel."""
    return f"{DERIVED_PREFIX}/{width}x{height}/{storage_path}"


def grid_crop_dir(grid_id: UUID, image_id: UUID) -> str:
    """Prefix holding one image's per-panel crops for one grid."""
    return f"{GRID_CROP_PREFIX}/{grid_id}/{image_id}/"


def _derived_keys(storage_path: str, panel_sizes: set[tuple[int, int]]) -> list[str]:
    keys = [thumb_key(storage_path, width) for width in ALLOWED_THUMB_WIDTHS]
    keys.extend(eink_preview_key(storage_path, step) for step in EINK_SATURATION_STEPS)
    keys.extend(derived_fit_key(storage_path, w, h) for w, h in panel_sizes)
    return keys


def _delete_objects(s3: S3Service, keys: list[str], crop_dirs: list[str]) -> None:
    """Best-effort removal; runs in a worker thread (the MinIO SDK blocks).

    Most derived keys never existed (a thumbnail width nobody requested);
    S3 deletes are idempotent, so attempting them is cheaper than a stat
    per key. Failures only leave orphans, which must not block deleting
    the row the operator asked to remove.
    """
    for prefix in crop_dirs:
        try:
            keys.extend(s3.list_keys(prefix))
        except S3Error:
            logger.warning("Failed to list grid crops under %s", prefix)
    for key in keys:
        try:
            s3.delete_object(key)
        except S3Error:
            logger.warning("Failed to delete S3 object %s", key)


async def delete_images(session: AsyncSession, s3: S3Service, images: list[Image]) -> None:
    """Delete images, their book links, display references and S3 objects.

    Does not commit; the caller owns the transaction. Display pointers to
    the image are cleared so no device or grid row names a vanished image.
    """
    if not images:
        return
    ids = [image.id for image in images]
    profiles = await session.exec(select(DeviceProfile.width, DeviceProfile.height))
    # Panel sizes in both orientations: derived copies are keyed by the
    # oriented size the panel was mounted at.
    panel_sizes = {size for w, h in profiles.all() for size in ((w, h), (h, w))}
    grid_ids = list((await session.exec(select(Grid.id))).all())

    keys: list[str] = []
    crop_dirs: list[str] = []
    for image in images:
        keys.append(image.storage_path)
        keys.extend(_derived_keys(image.storage_path, panel_sizes))
        crop_dirs.extend(grid_crop_dir(grid_id, image.id) for grid_id in grid_ids)
    await asyncio.to_thread(_delete_objects, s3, keys, crop_dirs)

    # SQLite does not enforce ON DELETE CASCADE / SET NULL here (foreign
    # keys are off), so the dependants are handled explicitly.
    await session.exec(delete(ImageBook).where(col(ImageBook.image_id).in_(ids)))
    await session.exec(update(Device).where(col(Device.current_image_id).in_(ids)).values(current_image_id=None))
    await session.exec(update(Grid).where(col(Grid.current_image_id).in_(ids)).values(current_image_id=None))
    for image in images:
        await session.delete(image)


async def delete_image(session: AsyncSession, s3: S3Service, image: Image) -> None:
    """Single-image form of :func:`delete_images`; does not commit."""
    await delete_images(session, s3, [image])
