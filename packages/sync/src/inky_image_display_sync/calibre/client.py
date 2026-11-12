"""Async client for a Calibre OPDS catalogue.

The whole library is paged in once and cached, and selection happens locally.
The server's own random feed (``/opds/discover``) takes no parameters and
ignores offset and limit, so server-side random and server-side filtering are
mutually exclusive. Holding the catalogue ourselves gives both at once — filter
on tags, language or author and *then* sample — and makes a shelf reproducible
from a seed, which the server can never offer.

Only plain Atom/OPDS elements are read: title, authors, publisher, language,
categories, summary and the cover link. Servers differ in what else they put
in an entry (Calibre-Web packs rating and series into a rendered blob, while
Calibre-Web Automated omits them), so nothing outside the standard elements is
relied on and an entry missing any of them degrades to ``None``.
"""

from __future__ import annotations

import html
import random
import re
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import httpx2
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    import logging
    from collections.abc import Collection, Sequence

    from inky_image_display_sync.calibre.config import CalibreConnectionConfig

_ATOM = "http://www.w3.org/2005/Atom"
_DCTERMS = "http://purl.org/dc/terms/"
_NS = {"a": _ATOM, "d": _DCTERMS}

# Both the full image and the thumbnail point at /opds/cover/<id>; the numeric
# id is the only handle the server exposes for a book in the feed.
_COVER_REL = "http://opds-spec.org/image"

# "00" is the "All" letter bucket, and the feed pages 60 at a time.
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
    authors: list[str] = []
    publisher: str | None = None
    language: str | None = None
    tags: list[str] = []
    description: str | None = None

    @property
    def author(self) -> str | None:
        """All authors as one display string; None when the entry names none."""
        return ", ".join(self.authors) or None

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
    authors: list[str] = []

    def matches(self, book: CalibreBook) -> bool:
        """Report whether the book satisfies every configured constraint."""
        return (
            _any_match(self.tags, book.tags)
            and _any_match(self.languages, [book.language])
            and _any_match(self.authors, book.authors)
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
    exclude: Collection[int] = (),
) -> list[CalibreBook]:
    """Filter the catalog then take a random sample of at most ``count``.

    ``exclude`` holds Calibre ids that must not be picked, e.g. books already
    on display.

    Passing a seed makes the shelf reproducible, which is what lets a failed
    generation be retried with the same books rather than a fresh set.
    """
    candidates = [b for b in books if b.book_id not in exclude and (book_filter is None or book_filter.matches(b))]
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

    Calibre stores descriptions as HTML, and some servers pass that markup
    through the summary escaped, so the text can arrive as literal ``<p>...</p>``
    with hard line wrapping. Tags and wrapping have to go before this is usable
    as prompt input.
    """
    return _WHITESPACE.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()


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

    summary = _text(entry, "a:summary")
    return CalibreBook(
        book_id=int(book_id),
        title=title,
        authors=[name for a in entry.findall("a:author/a:name", _NS) if (name := (a.text or "").strip())],
        publisher=_text(entry, "a:publisher/a:name"),
        language=_text(entry, "d:language"),
        # custom_column:* categories are the library's own columns (e.g. a
        # "Gelesen" read flag), whose label is the column's value ("True"),
        # not a tag, so they would pollute tag filters.
        tags=[
            label
            for c in entry.findall("a:category", _NS)
            if (label := c.get("label")) and not c.get("scheme", "").startswith("custom_column:")
        ],
        description=(_clean_description(summary) if summary else None) or None,
    )


def parse_catalog(xml: str) -> list[CalibreBook]:
    """Parse an OPDS feed into books, skipping entries we cannot address."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CalibreError(f"Malformed OPDS feed: {exc}") from exc
    return [book for entry in root.findall("a:entry", _NS) if (book := _parse_entry(entry)) is not None]


class CalibreClient:
    """Reads books and covers from a Calibre OPDS catalogue.

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
        self._auth = (
            httpx2.BasicAuth(config.username, config.password.get_secret_value())
            if config.username is not None and config.password is not None
            else None
        )
        self.logger = logger
        self._cache: list[CalibreBook] | None = None
        self._cached_at = 0.0

    async def _get(self, path: str) -> httpx2.Response:
        # Redirects stay off on purpose: every URL is built from base_url, so
        # credentials can only ever reach that host. A redirect (say, to a
        # login page on another host) is reported as an error instead of being
        # followed with an Authorization header.
        async with httpx2.AsyncClient(timeout=self.timeout, verify=self.verify_ssl, follow_redirects=False) as client:
            response = await client.get(f"{self.base_url}{path}", auth=self._auth)
        if response.status_code in (httpx2.codes.UNAUTHORIZED, httpx2.codes.FORBIDDEN):
            # Surfaced distinctly so a bad credential is never mistaken for an
            # empty library or a transient outage.
            hint = "" if self._auth else " (no CALIBRE_USERNAME/CALIBRE_PASSWORD configured)"
            raise CalibreError(
                f"Calibre OPDS rejected the credentials: GET {path} returned {response.status_code}{hint}"
            )
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
