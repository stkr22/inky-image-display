"""Pydantic models for Immich API responses.

All models use extra="ignore" for forward compatibility with new API fields.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class ImmichExifInfo(BaseModel):
    """EXIF metadata from Immich asset."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    city: str | None = None
    state: str | None = None
    country: str | None = None
    description: str | None = None
    date_time_original: datetime | None = Field(default=None, alias="dateTimeOriginal")
    make: str | None = None
    model: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: int | None = None
    exif_image_width: int | None = Field(default=None, alias="exifImageWidth")
    exif_image_height: int | None = Field(default=None, alias="exifImageHeight")


class ImmichPerson(BaseModel):
    """Person recognized in an Immich asset."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None


class ImmichAsset(BaseModel):
    """Asset response from Immich API.

    Maps to AssetResponseDto from Immich OpenAPI spec.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    type: Literal["IMAGE", "VIDEO"]
    original_file_name: str = Field(alias="originalFileName")
    original_mime_type: str = Field(alias="originalMimeType")
    checksum: str  # Base64 SHA1 for deduplication

    # Timestamps
    file_created_at: datetime = Field(alias="fileCreatedAt")
    local_date_time: datetime | None = Field(default=None, alias="localDateTime")

    # Dimensions (top-level fields from API, available on all endpoints)
    width: int | None = None
    height: int | None = None

    # Optional metadata
    exif_info: ImmichExifInfo | None = Field(default=None, alias="exifInfo")
    people: list[ImmichPerson] | None = None
    is_favorite: bool = Field(default=False, alias="isFavorite")


class ImmichAlbum(BaseModel):
    """Album from Immich API."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    album_name: str = Field(alias="albumName")
    description: str | None = None
    asset_count: int = Field(alias="assetCount")


# Response wrapper models for API endpoints


class RandomSearchResponse(RootModel[list[ImmichAsset]]):
    """Response from POST /search/random - returns list of assets directly."""


class AlbumsResponse(RootModel[list[ImmichAlbum]]):
    """Response from GET /albums - returns list of albums."""


class SearchAssetResponseDto(BaseModel):
    """Assets page in smart search response."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    total: int = 0
    count: int = 0
    items: list[ImmichAsset] = Field(default_factory=list)
    next_page: str | None = Field(default=None, alias="nextPage")


class SmartSearchResponse(BaseModel):
    """Response from POST /search/smart (SearchResponseDto).

    Only models the assets field - albums is not populated for smart search.
    """

    model_config = ConfigDict(extra="ignore")

    assets: SearchAssetResponseDto
