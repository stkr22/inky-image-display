"""App-wide tunable settings stored in the database.

A simple key/value table: each row holds one operator-tunable value as a
JSON-encoded scalar. Storing values as JSON keeps a single column type
while allowing future settings to be numbers, booleans, or short lists
without further migrations.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from inky_image_display_shared.time import utcnow


class AppSetting(SQLModel, table=True):
    """One operator-tunable setting keyed by name.

    Attributes:
        key: Setting name (primary key).
        value: JSON-encoded scalar value.
        updated_at: Last time this setting was written.

    """

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str = Field(description="JSON-encoded scalar value")
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow})
