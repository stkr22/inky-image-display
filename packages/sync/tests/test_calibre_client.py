"""Tests for parsing and selecting from a Calibre OPDS catalogue.

The fixture uses the plain Atom/OPDS elements the parser relies on, including
entries that are missing the optional ones.
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
  <title>Library</title>
  <entry>
    <title>Der Grüne Fluss</title>
    <author><name>Anna Bergström</name></author>
    <author><name>Jonas Lind</name></author>
    <publisher><name>dtv</name></publisher>
    <dcterms:language>deu</dcterms:language>
    <category term="Fantasy" label="Belletristik/Fantasy"/>
    <category term="Fantasy" label="Fantasy"/>
    <category scheme="custom_column:Gelesen" term="Gelesen" label="True"/>
    <summary>&lt;p&gt;Der dritte Band
der Nordlicht-Saga &amp;amp; Fortsetzung.&lt;/p&gt;</summary>
    <link type="image/jpeg" href="/opds/cover/769" rel="http://opds-spec.org/image"/>
    <link rel="http://opds-spec.org/acquisition" href="/opds/download/769/epub/"/>
  </entry>
  <entry>
    <title>Silent Harbour</title>
    <author><name>Peter Vane</name></author>
    <dcterms:language>eng</dcterms:language>
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
    assert book.authors == ["Anna Bergström", "Jonas Lind"]
    assert book.author == "Anna Bergström, Jonas Lind"
    assert book.publisher == "dtv"
    assert book.language == "deu"
    # The library's own columns (custom_column:*) are not tags.
    assert book.tags == ["Belletristik/Fantasy", "Fantasy"]
    # Descriptions may carry escaped HTML and hard wrapping, both flattened away.
    assert book.description == "Der dritte Band der Nordlicht-Saga & Fortsetzung."


def test_entry_without_optional_fields_degrades_to_none():
    book = parse_catalog(_FEED)[1]
    assert book.book_id == 945
    assert (book.description, book.publisher) == (None, None)
    assert book.tags == []


def test_entry_without_authors_has_no_author():
    entry = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>'
    entry += '<link href="/opds/cover/1" rel="http://opds-spec.org/image"/></entry></feed>'
    book = parse_catalog(entry)[0]
    assert book.authors == []
    assert book.author is None


def test_entry_without_cover_link_is_skipped():
    # No cover link means no book id, and without an id nothing downstream can
    # fetch the cover or dedupe the generated image.
    assert [b.title for b in parse_catalog(_FEED)] == ["Der Grüne Fluss", "Silent Harbour"]


def test_subject_line_names_title_and_authors():
    full, bare = parse_catalog(_FEED)[:2]
    assert full.as_subject() == '"Der Grüne Fluss" by Anna Bergström, Jonas Lind'
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
    tagged, bare = parse_catalog(_FEED)[:2]
    assert BookFilter(tags=["fantasy"]).matches(tagged)
    assert BookFilter(tags=["Fantasy", "History"]).matches(tagged)
    assert not BookFilter(tags=["History"]).matches(tagged)
    assert not BookFilter(tags=["Fantasy"]).matches(bare)


def test_author_filter_matches_any_of_a_books_authors():
    book = parse_catalog(_FEED)[0]
    assert BookFilter(authors=["jonas lind"]).matches(book)
    assert not BookFilter(authors=["Peter Vane"]).matches(book)


def test_filter_constraints_combine_as_and():
    book = parse_catalog(_FEED)[0]
    assert BookFilter(tags=["Fantasy"], languages=["deu"]).matches(book)
    assert not BookFilter(tags=["Fantasy"], languages=["eng"]).matches(book)


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

    client._get = fake_get
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


# --- authentication ---------------------------------------------------------


def _client_with_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    username: str | None = None,
    password: str | None = None,
) -> CalibreClient:
    """A client whose real ``_get`` runs against an in-process fake server."""
    real_client = httpx2.AsyncClient
    monkeypatch.setattr(
        "inky_image_display_sync.calibre.client.httpx2.AsyncClient",
        lambda **kwargs: real_client(transport=httpx2.MockTransport(handler), **kwargs),
    )
    return CalibreClient(
        CalibreConnectionConfig(base_url="http://calibre.invalid", username=username, password=password),
        logging.getLogger("test"),
    )


async def test_credentials_are_sent_as_basic_auth_on_catalog_and_cover(monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if "cover" in request.url.path:
            return httpx2.Response(200, content=b"img")
        return httpx2.Response(200, text=_page(1, 1))

    client = _client_with_transport(monkeypatch, handler, username="inky", password="s3cret")
    await client.fetch_catalog()
    await client.fetch_cover(1)

    # The expected value is the base64 encoding of inky:s3cret.
    assert len(seen) == 2
    assert all(r.headers["Authorization"] == "Basic aW5reTpzM2NyZXQ=" for r in seen)


async def test_no_credentials_means_no_authorization_header(monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text=_page(1, 1))

    client = _client_with_transport(monkeypatch, handler)
    await client.fetch_catalog()

    assert "Authorization" not in seen[0].headers


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_credentials_raise_an_explicit_error(monkeypatch, status):
    client = _client_with_transport(monkeypatch, lambda _r: httpx2.Response(status), username="inky", password="wrong")
    with pytest.raises(CalibreError, match="rejected the credentials") as exc_info:
        await client.fetch_catalog()
    # The error text ends up in logs and the job's status, so the secret must not.
    assert "wrong" not in str(exc_info.value)


async def test_unauthorised_without_credentials_points_at_the_missing_config(monkeypatch):
    client = _client_with_transport(monkeypatch, lambda _r: httpx2.Response(401))
    with pytest.raises(CalibreError, match="CALIBRE_USERNAME"):
        await client.fetch_catalog()


async def test_redirects_are_not_followed_so_credentials_stay_on_the_base_host(monkeypatch):
    hosts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        hosts.append(request.url.host)
        return httpx2.Response(302, headers={"Location": "http://elsewhere.invalid/opds"})

    client = _client_with_transport(monkeypatch, handler, username="inky", password="s3cret")
    with pytest.raises(CalibreError, match="302"):
        await client.fetch_catalog()

    assert hosts == ["calibre.invalid"]


def test_half_a_credential_pair_is_rejected_at_startup():
    with pytest.raises(ValueError, match="set together"):
        CalibreConnectionConfig(base_url="http://calibre.invalid", username="inky")
    with pytest.raises(ValueError, match="set together"):
        CalibreConnectionConfig(base_url="http://calibre.invalid", password="s3cret")


def test_password_is_masked_in_config_repr():
    config = CalibreConnectionConfig(base_url="http://calibre.invalid", username="inky", password="s3cret")
    assert "s3cret" not in repr(config)


def test_plain_http_with_credentials_warns_at_startup(caplog: pytest.LogCaptureFixture):
    # Rejecting would break common LAN setups, but the operator should know
    # the password travels unencrypted.
    with caplog.at_level(logging.WARNING, logger="test"):
        CalibreClient(
            CalibreConnectionConfig(base_url="http://calibre.lan", username="u", password="p"),
            logging.getLogger("test"),
        )
    assert any("unencrypted" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("base_url", "username", "password"),
    [("https://calibre.lan", "u", "p"), ("http://calibre.lan", None, None)],
    ids=["https-with-credentials", "http-anonymous"],
)
def test_no_warning_without_cleartext_credentials(caplog: pytest.LogCaptureFixture, base_url, username, password):
    with caplog.at_level(logging.WARNING, logger="test"):
        CalibreClient(
            CalibreConnectionConfig(base_url=base_url, username=username, password=password),
            logging.getLogger("test"),
        )
    assert not caplog.records
