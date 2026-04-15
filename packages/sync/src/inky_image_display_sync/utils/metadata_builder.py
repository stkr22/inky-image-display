"""Natural language metadata builder for images."""

from datetime import datetime

# Constants for name formatting
_PAIR_COUNT = 2


class MetadataBuilder:
    """Build natural language metadata from image data.

    Generates human-readable title and description strings from structured
    metadata like people names, location, date, and album information.
    """

    @staticmethod
    def build_title(
        people: list[str] | None = None,
        city: str | None = None,
        country: str | None = None,
        date: datetime | None = None,
    ) -> str | None:
        """Build short title for voice responses.

        Priority: People > Location > Date
        Examples: "John and Sarah, Berlin" or "Berlin, August 2023"

        Args:
            people: List of recognized person names
            city: City name from EXIF
            country: Country name from EXIF
            date: Date photo was taken

        Returns:
            Short title string or None if no data available

        """
        parts: list[str] = []

        # People names (max 2 shown)
        if people:
            parts.append(_format_names_short(people))

        # Location (city preferred, country as fallback if no people)
        if city:
            parts.append(city)
        elif country and not people:
            parts.append(country)

        # Date (only if no people, to keep title short)
        if date and not people:
            parts.append(date.strftime("%B %Y"))

        return ", ".join(parts) if parts else None

    @staticmethod
    def build_description(  # noqa: PLR0913
        people: list[str] | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        date: datetime | None = None,
        album_names: list[str] | None = None,
    ) -> str | None:
        """Build full description combining all metadata.

        Examples:
        - "John and Sarah in Berlin, Germany - August 2023. From album: Summer Vacation"
        - "Photo from San Francisco, California - March 2024"
        - "Photo of Emma and Michael. From album: Family"

        Args:
            people: List of recognized person names
            city: City name from EXIF
            state: State/region from EXIF
            country: Country name from EXIF
            date: Date photo was taken
            album_names: List of album names containing this image

        Returns:
            Full description string or None if no data available

        """
        sentences: list[str] = []

        # Main sentence: people + location
        location = _build_location(city, state, country)
        if people and location:
            names = _format_names_full(people)
            sentences.append(f"{names} in {location}")
        elif people:
            sentences.append(f"Photo of {_format_names_full(people)}")
        elif location:
            sentences.append(f"Photo from {location}")

        # Append date to last sentence
        if date:
            date_str = date.strftime("%B %Y")
            if sentences:
                sentences[-1] += f" - {date_str}"
            else:
                sentences.append(f"Photo from {date_str}")

        # Album info as separate sentence
        if album_names:
            albums = ", ".join(album_names[:2])  # Max 2 albums
            sentences.append(f"From album: {albums}")

        return ". ".join(sentences) if sentences else None


def _format_names_short(names: list[str]) -> str:
    """Format names for short title (max 2 shown)."""
    if len(names) == 1:
        return names[0]
    if len(names) == _PAIR_COUNT:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]} and others"


def _format_names_full(names: list[str]) -> str:
    """Format names for full description."""
    if len(names) == 1:
        return names[0]
    if len(names) == _PAIR_COUNT:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]}, {names[1]}, and {len(names) - _PAIR_COUNT} others"


def _build_location(
    city: str | None,
    state: str | None,
    country: str | None,
) -> str | None:
    """Build location string from components."""
    parts = [p for p in [city, state, country] if p]
    return ", ".join(parts) if parts else None
