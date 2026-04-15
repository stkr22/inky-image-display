"""Pydantic models for Immich API request payloads.

Uses alias_generator for automatic snake_case to camelCase conversion,
matching the Immich API's expected format.
"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseSearchPayload(BaseModel):
    """Base payload for Immich search APIs.

    All fields use snake_case internally but serialize to camelCase for the API.
    Fields set to None are excluded from the payload.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    size: int = Field(default=10)
    album_ids: list[str] | None = None
    person_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    is_favorite: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    taken_after: str | None = None  # ISO format string
    taken_before: str | None = None  # ISO format string
    rating: int | None = None
    type: str = "IMAGE"  # Always IMAGE for this skill


class RandomSearchPayload(BaseSearchPayload):
    """Payload for POST /search/random endpoint.

    Includes withExif and withPeople flags to get complete asset data.
    """

    with_exif: bool = True
    with_people: bool = True


class SmartSearchPayload(BaseSearchPayload):
    """Payload for POST /search/smart endpoint (CLIP semantic search).

    Note: Smart search doesn't support withPeople/withExif parameters.
    Use get_asset() to fetch full details after smart search.
    """

    query: str  # Required for smart search
