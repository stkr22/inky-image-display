"""Async client for the Calibre-Web OPDS catalog.

The whole library is paged in once and cached, and selection happens locally.
Calibre-Web's own random feed (``/opds/discover``) takes no parameters and
ignores offset and limit, so server-side random and server-side filtering are
mutually exclusive. Holding the catalog ourselves gives both at once — filter
on tags, language, series or rating and *then* sample — and makes a shelf
reproducible from a seed, which the server can never offer.

The catalog is Atom XML rather than JSON, and Calibre-Web packs the fields we
care about into two places: proper Atom elements for title, author, publisher,
language and cover, and a rendered XHTML blob in ``<content>`` that carries
rating, tags, series and the description. The blob is parsed with the XML tree
rather than by scraping strings so an entry missing any of those degrades to
``None`` instead of shifting the other fields.
"""

from __future__ import annotations

import html
import random
import re
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import httpx2
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence

    from inky_image_display_sync.calibre.config import CalibreConnectionConfig

_ATOM = "http://www.w3.org/2005/Atom"
_XHTML = "http://www.w3.org/1999/xhtml"
_DCTERMS = "http://purl.org/dc/terms/"
_NS = {"a": _ATOM, "x": _XHTML, "d": _DCTERMS}

# Both the full image and the thumbnail point at /opds/cover/<id>; the numeric
# id is the only handle Calibre-Web exposes for a book in the feed.
_COVER_REL = "http://opds-spec.org/image"

# "00" is Calibre-Web's "All" letter bucket, and the feed pages 60 at a time.
_CATALOG_PATH = "/opds/books/letter/00"
_PAGE_SIZE = 60
# Backstop against an endpoint that never returns a short page.
_MAX_PAGES = 200

# Above this, a title is cut back to the part before its first colon so it
# still fits a painted spine.
SPINE_TITLE_MAX_LENGTH = 40


class CalibreError(RuntimeError):
    """Raised when the catalog cannot be read or parsed."""


class CalibreBook(BaseModel):
    """One book from the OPDS catalog."""

    model_config = ConfigDict(extra="ignore")

    book_id: int
    title: str
    author: str | None = None
    publisher: str | None = None
    language: str | None = None
    series: str | None = None
    series_index: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = []
    description: str | None = None

    def short_title(self, max_length: int = SPINE_TITLE_MAX_LENGTH) -> str:
        """Return the title trimmed to its main heading, for spine lettering.

        Calibre titles routinely carry a subtitle after a colon —
        "Fundament: Warum komplexe Systeme scheitern". A spine has room for
        the heading and not much else, and long strings are also where the
        image model's lettering starts to break down, so anything over
        ``max_length`` is cut at its first colon. Titles that are merely long
        with no colon are left intact: there is no safe place to cut them.
        """
        if len(self.title) <= max_length or ":" not in self.title:
            return self.title
        return self.title.split(":", 1)[0].strip() or self.title

    def as_subject(self) -> str:
        """One-line description used as the generation subject."""
        parts = [f'"{self.title}"']
        if self.author:
            parts.append(f"by {self.author}")
        if self.series:
            index = f" #{self.series_index}" if self.series_index else ""
            parts.append(f"({self.series}{index})")
        return " ".join(parts)


class BookFilter(BaseModel):
    """Which books a job is willing to display.

    Every field is an independent AND; the list fields match if *any* of their
    values match, so ``tags=["Fantasy", "Science Fiction"]`` means either. All
    string matching is case-insensitive because Calibre tags are entered by
    hand and their casing drifts.
    """

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = []
    languages: list[str] = []
    series: list[str] = []
    authors: list[str] = []
    min_rating: int | None = Field(default=None, ge=1, le=5)

    def matches(self, book: CalibreBook) -> bool:
        """Report whether the book satisfies every configured constraint."""
        if self.min_rating is not None and (book.rating or 0) < self.min_rating:
            return False
        return (
            _any_match(self.tags, book.tags)
            and _any_match(self.languages, [book.language])
            and _any_match(self.series, [book.series])
            and _any_match(self.authors, [book.author])
        )


def _any_match(wanted: Sequence[str], actual: Sequence[str | None]) -> bool:
    """Match when nothing is wanted, or when any actual value is among the wanted."""
    if not wanted:
        return True
    lowered = {value.lower() for value in actual if value}
    return any(candidate.lower() in lowered for candidate in wanted)


def select_books(
    books: list[CalibreBook],
    count: int,
    book_filter: BookFilter | None = None,
    seed: int | None = None,
) -> list[CalibreBook]:
    """Filter the catalog then take a random sample of at most ``count``.

    Passing a seed makes the shelf reproducible, which is what lets a failed
    generation be retried with the same books rather than a fresh set.
    """
    candidates = [b for b in books if book_filter is None or book_filter.matches(b)]
    if len(candidates) <= count:
        return candidates
    return random.Random(seed).sample(candidates, count)


def _text(entry: ET.Element, path: str) -> str | None:
    value = entry.findtext(path, namespaces=_NS)
    return value.strip() if value and value.strip() else None


_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _clean_description(text: str) -> str:
    """Flatten a description into a single line of plain prose.

    Calibre stores descriptions as HTML and Calibre-Web escapes that markup
    inside the feed's own XHTML, so the parsed text arrives as a literal
    ``<p>...</p>`` string wrapped at the source's line width. Both the tags and
    the hard wrapping have to go before this is usable as prompt input.
    """
    return _WHITESPACE.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()


def _parse_series(blob: str) -> tuple[str | None, str | None]:
    """Pull ``SERIES: Name [index]`` out of the rendered content blob."""
    _, _, rest = blob.partition("SERIES:")
    line = rest.splitlines()[0].strip() if rest else ""
    if not line:
        return None, None
    name, sep, index = line.rpartition("[")
    if not sep:
        return line, None
    return name.strip() or None, index.rstrip("]").strip() or None


def _parse_rating(blob: str) -> int | None:
    """Count the stars on the ``RATING:`` line; unrated books have no line."""
    _, _, rest = blob.partition("RATING:")
    stars = rest.splitlines()[0].count("★") if rest else 0
    return stars or None


def _parse_entry(entry: ET.Element) -> CalibreBook | None:
    """Build a book from one Atom entry; None when it has no usable cover id."""
    title = _text(entry, "a:title")
    cover_href = next(
        (link.get("href", "") for link in entry.findall("a:link", _NS) if link.get("rel") == _COVER_REL),
        "",
    )
    book_id = cover_href.rstrip("/").rpartition("/")[2]
    if not title or not book_id.isdigit():
        return None

    content = entry.find("a:content/x:div", _NS)
    blob = "".join(content.itertext()) if content is not None else ""
    series, series_index = _parse_series(blob)
    # Calibre-Web renders the description as the trailing <p> of the blob;
    # books without one simply have no paragraph.
    paragraphs = content.findall("x:p", _NS) if content is not None else []
    description = _clean_description("".join(paragraphs[0].itertext())) if paragraphs else None

    return CalibreBook(
        book_id=int(book_id),
        title=title,
        author=_text(entry, "a:author/a:name"),
        publisher=_text(entry, "a:publisher/a:name"),
        language=_text(entry, "d:language"),
        series=series,
        series_index=series_index,
        rating=_parse_rating(blob),
        tags=[label for c in entry.findall("a:category", _NS) if (label := c.get("label"))],
        description=description or None,
    )


def parse_catalog(xml: str) -> list[CalibreBook]:
    """Parse an OPDS feed into books, skipping entries we cannot address."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CalibreError(f"Malformed OPDS feed: {exc}") from exc
    return [book for entry in root.findall("a:entry", _NS) if (book := _parse_entry(entry)) is not None]


class CalibreClient:
    """Reads books and covers from Calibre-Web's OPDS catalog.

    The catalog is cached in memory for ``cache_ttl_seconds`` because paging the
    whole library costs a request per 60 books and a home library changes far
    more slowly than jobs run.
    """

    def __init__(self, config: CalibreConnectionConfig, logger: logging.Logger) -> None:
        """Capture connection settings; the HTTP client is created per call."""
        self.base_url = str(config.base_url).rstrip("/")
        self.timeout = config.timeout_seconds
        self.verify_ssl = config.verify_ssl
        self.cache_ttl_seconds = config.cache_ttl_seconds
        self.logger = logger
        self._cache: list[CalibreBook] | None = None
        self._cached_at = 0.0

    async def _get(self, path: str) -> httpx2.Response:
        async with httpx2.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
            response = await client.get(f"{self.base_url}{path}")
        if response.status_code != httpx2.codes.OK:
            raise CalibreError(f"GET {path} returned {response.status_code}")
        return response

    async def fetch_catalog(self, refresh: bool = False) -> list[CalibreBook]:
        """Return the whole library, paging the feed on a cache miss."""
        if not refresh and self._cache is not None and time.monotonic() - self._cached_at < self.cache_ttl_seconds:
            return self._cache

        books: list[CalibreBook] = []
        for page in range(_MAX_PAGES):
            offset = page * _PAGE_SIZE
            batch = parse_catalog((await self._get(f"{_CATALOG_PATH}?offset={offset}")).text)
            books.extend(batch)
            # A short page is the last one; the feed exposes no total count.
            if len(batch) < _PAGE_SIZE:
                break
        else:
            self.logger.warning("Calibre catalog stopped at the %d page cap", _MAX_PAGES)

        self._cache = books
        self._cached_at = time.monotonic()
        self.logger.info("Calibre catalog: %d books", len(books))
        return books

    async def select(
        self,
        count: int,
        book_filter: BookFilter | None = None,
        seed: int | None = None,
    ) -> list[CalibreBook]:
        """Fetch (or reuse) the catalog and sample ``count`` books from it."""
        return select_books(await self.fetch_catalog(), count, book_filter, seed)

    async def fetch_cover(self, book_id: int) -> bytes:
        """Fetch a book's cover image bytes.

        The ``thumb_*`` and ``cover_*`` paths are aliases for the full image
        rather than resized variants, so there is nothing cheaper worth asking
        for; callers downscale before use.
        """
        return (await self._get(f"/opds/cover/{book_id}")).content
