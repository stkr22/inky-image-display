"""Image groups: panel spreads shown together on a grid.

A group assigns images to grid slots so every panel shows its piece of
the spread simultaneously — the one standardized shape for coordinated
multi-screen content. Two flavours share the table:

* Worker-generated groups (``display_job_id`` set): a display job's run
  renders one image per grid slot (MOTD screens today). Read-only —
  the job re-creates them; operators can only delete.
* Operator-created groups: existing library images assigned to slots by
  hand — the manual counterpart of a worker run. Images without a slot
  are not shown until assigned; several images on one slot rotate on
  that panel, one step per grid refresh.

(Cover-cropping ONE image across all panels is not a group — that is a
loose pool image via ``Image.target_grid_id``.)

Images referencing a group are excluded from solo and grid-pool rotation;
the grid's queue interleaves groups with loose pool images.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class ImageGroup(SQLModel, table=True):
    """A spread of slot-assigned images shown together on one grid."""

    __tablename__ = "image_groups"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    # The grid whose queue this group belongs to. SET NULL keeps the group
    # (and its images) when the grid is deleted; a group without a grid is
    # inert until re-targeted.
    target_grid_id: UUID | None = Field(default=None, foreign_key="grids.id", ondelete="SET NULL", index=True)
    # Provenance: the display job whose run generated this group, if any.
    display_job_id: UUID | None = Field(default=None, foreign_key="display_jobs.id", ondelete="SET NULL", index=True)
    # Story metadata for generated groups (shown in the UI, drives the QR part).
    description: str | None = Field(default=None)
    source_url: str | None = Field(default=None)

    # Position within the grid's queue; shared sequence with loose pool
    # images (Image.queue_position) so operators can interleave both.
    queue_position: int = Field(default=0)
    last_displayed_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})
