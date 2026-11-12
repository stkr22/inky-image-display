"""Which books are on which images, and which books are currently in use.

The point of the tracking is to stop one book appearing on two walls at once,
so the cases that matter are the ones that decide whether a book counts as "in
use": a live image, an expired one, and one that has been deleted.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from inky_image_display_shared.time import utcnow


def _register(client: TestClient, books: list[tuple[int, str]], **extra) -> str:
    resp = client.post(
        "/api/images/register",
        json={
            "source_name": "calibre",
            "storage_path": f"ai/calibre/{books[0][0]}.jpg",
            "books": [{"book_id": book_id, "title": title} for book_id, title in books],
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_image_lists_its_books_in_reading_order(client: TestClient):
    image_id = _register(client, [(7, "Seven"), (3, "Three"), (9, "Nine")])

    books = client.get(f"/api/images/{image_id}/books").json()

    assert [(b["position"], b["book_id"], b["title"]) for b in books] == [
        (0, 7, "Seven"),
        (1, 3, "Three"),
        (2, 9, "Nine"),
    ]


def test_image_without_books_has_an_empty_list(client: TestClient):
    resp = client.post("/api/images/register", json={"storage_path": "immich/x.jpg"})

    assert client.get(f"/api/images/{resp.json()['id']}/books").json() == []


def test_used_books_span_every_live_image(client: TestClient):
    _register(client, [(1, "One"), (2, "Two")])
    _register(client, [(2, "Two"), (3, "Three")])

    assert client.get("/api/calibre/jobs/used-books").json() == [1, 2, 3]


def test_expired_images_free_their_books(client: TestClient):
    past = (utcnow() - timedelta(days=1)).isoformat()
    future = (utcnow() + timedelta(days=1)).isoformat()
    _register(client, [(1, "Lapsed")], expires_at=past)
    _register(client, [(2, "Retained")], expires_at=future)

    assert client.get("/api/calibre/jobs/used-books").json() == [2]


def test_deleting_an_image_frees_its_books(client: TestClient):
    image_id = _register(client, [(1, "One"), (2, "Two")])
    assert client.get("/api/calibre/jobs/used-books").json() == [1, 2]

    assert client.delete(f"/api/images/{image_id}").status_code == 204

    assert client.get("/api/calibre/jobs/used-books").json() == []
    assert client.get(f"/api/images/{image_id}/books").json() == []


def test_images_out_of_solo_rotation_still_hold_their_books(client: TestClient):
    """'In use' means the image exists and has not lapsed, not that it is in the solo pool.

    An excluded image can still be pushed by hand, and a grouped one is shown
    through its grid, so both must keep their books off other shelves.
    """
    excluded = _register(client, [(1, "Excluded")])
    assert client.put(f"/api/images/{excluded}", json={"excluded_from_rotation": True}).status_code == 200
    grouped = _register(client, [(2, "Grouped")])
    spread = client.post(
        "/api/image-groups", json={"name": "spread", "members": [{"image_id": grouped, "row": 0, "col": 0}]}
    )
    assert spread.status_code == 201, spread.text

    assert client.get("/api/calibre/jobs/used-books").json() == [1, 2]
