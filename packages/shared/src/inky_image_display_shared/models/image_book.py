"""Which Calibre books an image shows.

An image only carries its books as free text in the title, which cannot answer
"is this book already on a wall?". One row per book per image makes that a
query. ``title`` is a snapshot so an image still reads correctly after the book
is renamed or removed from Calibre.
"""

from uuid import UUID

from sqlmodel import Field, SQLModel


class ImageBook(SQLModel, table=True):
    """A book shown on an image, in reading order (top shelf first, left to right)."""

    __tablename__ = "image_books"

    image_id: UUID = Field(foreign_key="images.id", primary_key=True, ondelete="CASCADE")
    position: int = Field(primary_key=True, description="Reading order within the image")
    book_id: int = Field(index=True, description="Calibre book id")
    title: str = Field(description="Title at the time the image was made")
