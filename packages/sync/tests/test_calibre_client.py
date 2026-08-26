"""Tests for parsing and selecting from the Calibre-Web OPDS catalog.

The fixture mirrors the real feed's shape: metadata split between Atom
elements and a rendered XHTML blob, with entries that are missing the
description, series, rating or categories that a full entry carries.
"""

import logging

import httpx2
import pytest
from inky_image_display_sync.calibre.client import (
    BookFilter,
    CalibreClient,
    CalibreError,
    parse_catalog,
    select_books,
)
from inky_image_display_sync.calibre.config import CalibreConnectionConfig

_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dcterms="http://purl.org/dc/terms/">
  <title>Calibre-Web</title>
  <entry>
    <title>Der Grüne Fluss</title>
    <author><name>Anna Bergström</name></author>
    <publisher><name>dtv</name></publisher>
    <dcterms:language>deu</dcterms:language>
    <category term="Fantasy" label="Belletristik/Fantasy"/>
    <category term="Fantasy" label="Fantasy"/>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">
      RATING: &#9733;&#9733;&#9733;&#9733;<br/>
      TAGS: Belletristik/Fantasy, Fantasy<br/>
      SERIES: Nordlicht-Saga [5]<br/>
      <p>&lt;p&gt;Der dritte Band
der Nordlicht-Saga &amp;amp; Fortsetzung.&lt;/p&gt;</p>
    </div></content>
    <link type="image/jpeg" href="/opds/cover/769" rel="http://opds-spec.org/image"/>
    <link rel="http://opds-spec.org/acquisition" href="/opds/download/769/epub/"/>
  </entry>
  <entry>
    <title>Silent Harbour</title>
    <author><name>Peter Vane</name></author>
    <dcterms:language>eng</dcterms:language>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">
      TAGS: <br/>
    </div></content>
    <link type="image/jpeg" href="/opds/cover/945" rel="http://opds-spec.org/image"/>
  </entry>
  <entry>
    <title>Unaddressable</title>
    <author><name>Nobody</name></author>
  </entry>
</feed>
"""


def test_parses_full_entry():
    book = parse_catalog(_FEED)[0]
    assert book.book_id == 769
    assert book.title == "Der Grüne Fluss"
    assert book.author == "Anna Bergström"
    assert book.publisher == "dtv"
    assert book.language == "deu"
    assert book.series == "Nordlicht-Saga"
    assert book.series_index == "5"
    assert book.rating == 4
    assert book.tags == ["Belletristik/Fantasy", "Fantasy"]
    # Calibre-Web escapes the description's own HTML inside the feed's XHTML
    # and hard-wraps it, so both have to be flattened away.
    assert book.description == "Der dritte Band der Nordlicht-Saga & Fortsetzung."


def test_entry_without_optional_fields_degrades_to_none():
    book = parse_catalog(_FEED)[1]
    assert book.book_id == 945
    assert (book.series, book.series_index, book.rating, book.description, book.publisher) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert book.tags == []


def test_entry_without_cover_link_is_skipped():
    # No cover link means no book id, and without an id nothing downstream can
    # fetch the cover or dedupe the generated image.
    assert [b.title for b in parse_catalog(_FEED)] == ["Der Grüne Fluss", "Silent Harbour"]


def test_subject_line_includes_series_when_present():
    full, bare = parse_catalog(_FEED)[:2]
    assert full.as_subject() == '"Der Grüne Fluss" by Anna Bergström (Nordlicht-Saga #5)'
    assert bare.as_subject() == '"Silent Harbour" by Peter Vane'


def test_short_title_cuts_a_long_title_at_its_subtitle_colon():
    book = parse_catalog(_FEED)[0].model_copy(
        update={"title": "Fundament: Warum komplexe Systeme reihenweise scheitern"}
    )
    assert book.short_title() == "Fundament"


def test_short_title_leaves_titles_that_already_fit():
    book = parse_catalog(_FEED)[0].model_copy(update={"title": "Nachtwache: Ein Bericht"})
    assert book.short_title() == "Nachtwache: Ein Bericht"


def test_short_title_keeps_a_long_title_that_has_no_colon():
    # Nowhere safe to cut, so a long spine beats a truncated one.
    long_title = "Ein sehr langer Titel ohne jeden Doppelpunkt und ohne Ende"
    book = parse_catalog(_FEED)[0].model_copy(update={"title": long_title})
    assert book.short_title() == long_title


def test_short_title_ignores_a_leading_colon():
    # Splitting would leave nothing to print, so keep the original.
    book = parse_catalog(_FEED)[0].model_copy(update={"title": ": " + "x" * 60})
    assert book.short_title() == ": " + "x" * 60


def test_malformed_feed_raises():
    with pytest.raises(CalibreError):
        parse_catalog("<feed><entry></feed>")


def test_filter_matches_any_listed_value_case_insensitively():
    rated, bare = parse_catalog(_FEED)[:2]
    assert BookFilter(tags=["fantasy"]).matches(rated)
    assert BookFilter(tags=["Fantasy", "History"]).matches(rated)
    assert not BookFilter(tags=["History"]).matches(rated)
    assert not BookFilter(tags=["Fantasy"]).matches(bare)


def test_filter_constraints_combine_as_and():
    rated = parse_catalog(_FEED)[0]
    assert BookFilter(tags=["Fantasy"], languages=["deu"], min_rating=4).matches(rated)
    assert not BookFilter(tags=["Fantasy"], languages=["eng"]).matches(rated)


def test_unrated_book_never_satisfies_a_minimum_rating():
    bare = parse_catalog(_FEED)[1]
    assert not BookFilter(min_rating=1).matches(bare)


def test_empty_filter_matches_everything():
    assert all(BookFilter().matches(b) for b in parse_catalog(_FEED))


def test_select_returns_all_when_fewer_candidates_than_requested():
    books = parse_catalog(_FEED)
    assert len(select_books(books, count=10)) == 2


def test_select_is_reproducible_for_a_seed_and_varies_without_one():
    books = parse_catalog(_FEED)
    assert select_books(books, 1, seed=7) == select_books(books, 1, seed=7)
    # Different seeds must be able to reach different books, or "reproducible"
    # would just mean "always the same book".
    assert {select_books(books, 1, seed=s)[0].title for s in range(20)} == {"Der Grüne Fluss", "Silent Harbour"}


def test_select_applies_the_filter_before_sampling():
    books = parse_catalog(_FEED)
    picked = select_books(books, count=10, book_filter=BookFilter(languages=["eng"]))
    assert [b.title for b in picked] == ["Silent Harbour"]


def _page(count: int, first_id: int) -> str:
    """A feed of ``count`` minimal entries, enough to be parsed and counted."""
    entries = "".join(
        f"<entry><title>Book {first_id + i}</title>"
        f'<link href="/opds/cover/{first_id + i}" rel="http://opds-spec.org/image"/></entry>'
        for i in range(count)
    )
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'


def _client_paging(pages: list[str]) -> tuple[CalibreClient, list[str]]:
    """A client whose HTTP layer replays ``pages`` and records requested paths."""
    client = CalibreClient(
        CalibreConnectionConfig(base_url="http://calibre.invalid"),
        logging.getLogger("test"),
    )
    requested: list[str] = []

    async def fake_get(path: str) -> httpx2.Response:
        requested.append(path)
        return httpx2.Response(200, text=pages[len(requested) - 1])

    client._get = fake_get  # ty: ignore[invalid-assignment]
    return client, requested


async def test_catalog_pages_until_a_short_page():
    # The feed exposes no total count, so a page of fewer than 60 is the only
    # signal that the library has been read to the end.
    client, requested = _client_paging([_page(60, 1), _page(60, 61), _page(13, 121)])
    books = await client.fetch_catalog()
    assert len(books) == 133
    assert requested == [
        "/opds/books/letter/00?offset=0",
        "/opds/books/letter/00?offset=60",
        "/opds/books/letter/00?offset=120",
    ]


async def test_catalog_is_cached_and_refresh_forces_a_reread():
    client, requested = _client_paging([_page(5, 1), _page(5, 1)])
    await client.fetch_catalog()
    await client.fetch_catalog()
    assert len(requested) == 1
    await client.fetch_catalog(refresh=True)
    assert len(requested) == 2


async def test_zero_ttl_disables_the_cache():
    client, requested = _client_paging([_page(5, 1), _page(5, 1)])
    client.cache_ttl_seconds = 0
    await client.fetch_catalog()
    await client.fetch_catalog()
    assert len(requested) == 2
