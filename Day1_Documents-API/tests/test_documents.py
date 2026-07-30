"""End-to-end tests for the Documents API against a real Postgres.

Count: 16 tests. Error cases (>=3): duplicate->409, get-missing->404,
delete-missing->404, plus validation->422 (including a bad publish date).
"""


# ---------- happy paths ----------

def test_create_document_returns_201_and_body(client, sample_payload):
    resp = client.post("/documents", json=sample_payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["url"] == sample_payload["url"]
    assert "created_at" in body


def test_get_document_by_id(client, sample_payload):
    created = client.post("/documents", json=sample_payload).json()
    resp = client.get(f"/documents/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == sample_payload["title"]


def test_delete_document_then_gone(client, sample_payload):
    created = client.post("/documents", json=sample_payload).json()
    assert client.delete(f"/documents/{created['id']}").status_code == 204
    # After delete it must be a 404.
    assert client.get(f"/documents/{created['id']}").status_code == 404


def test_list_filters_by_source(client, sample_payload):
    client.post("/documents", json={**sample_payload, "url": "https://a.com", "source": "blog"})
    client.post("/documents", json={**sample_payload, "url": "https://b.com", "source": "docs"})
    resp = client.get("/documents", params={"source": "docs"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "docs"


def test_list_pagination_limit_and_offset(client, sample_payload):
    for i in range(5):
        client.post("/documents", json={**sample_payload, "url": f"https://x.com/{i}"})
    page1 = client.get("/documents", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/documents", params={"limit": 2, "offset": 2}).json()
    assert [r["id"] for r in page1] == [1, 2]
    assert [r["id"] for r in page2] == [3, 4]  # no overlap, no gap


def test_list_empty_returns_empty_array(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------- error cases ----------

def test_duplicate_url_returns_409_not_500(client, sample_payload):
    assert client.post("/documents", json=sample_payload).status_code == 201
    # Same url again -> the DB unique constraint rejects it -> 409.
    dup = client.post("/documents", json=sample_payload)
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"].lower()


def test_get_missing_returns_404(client):
    assert client.get("/documents/999999").status_code == 404


def test_delete_missing_returns_404(client):
    assert client.delete("/documents/999999").status_code == 404


def test_missing_field_returns_422(client):
    # No 'url' -> Pydantic validation rejects before hitting the DB.
    resp = client.post("/documents", json={"title": "t", "text": "x", "source": "s"})
    assert resp.status_code == 422


def test_empty_title_returns_422(client, sample_payload):
    # min_length=1 in the schema rejects empty strings.
    resp = client.post("/documents", json={**sample_payload, "title": ""})
    assert resp.status_code == 422


# ---------- published_at (migration 0002) ----------
#
# published_at is the AUTHOR's publish date, distinct from created_at, which is
# when we stored the row. The crawler in Day 3 fills it in when it can extract
# one and leaves it null when it cannot -- so both paths need to work.

def test_omitting_published_at_stores_null(client, sample_payload):
    """The backwards-compatibility test, and the most important one here.

    sample_payload has no published_at at all -- it is exactly the body every
    pre-migration client sends. That must still succeed (201), and the missing
    date must be stored as null rather than defaulted to something invented.
    """
    resp = client.post("/documents", json=sample_payload)
    assert resp.status_code == 201
    assert resp.json()["published_at"] is None


def test_published_at_round_trips(client, sample_payload):
    """A supplied date survives the write and comes back on read."""
    resp = client.post(
        "/documents",
        json={**sample_payload, "published_at": "2019-03-14T09:30:00Z"},
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # Re-fetch rather than trusting the POST response: this proves the value
    # reached Postgres and came back, not just that it echoed through Pydantic.
    fetched = client.get(f"/documents/{doc_id}").json()
    assert fetched["published_at"] is not None
    assert fetched["published_at"].startswith("2019-03-14T09:30:00")


def test_published_at_is_independent_of_created_at(client, sample_payload):
    """The whole reason the column exists: the two dates differ.

    An article published in 2019 that we crawl today must show 2019 as its
    publish date and today as its created_at. If a future refactor ever made
    one an alias of the other, this test fails.
    """
    resp = client.post(
        "/documents",
        json={**sample_payload, "published_at": "2019-03-14T09:30:00Z"},
    )
    body = resp.json()
    assert body["published_at"].startswith("2019")
    assert not body["created_at"].startswith("2019")


def test_unparseable_published_at_returns_422(client, sample_payload):
    """Garbage in the date field is rejected at the edge, not stored.

    A crawler that scraped "last Tuesday" out of a page must not be able to
    push that into the table. Pydantic parses the field, so this is a 422
    before any SQL runs.
    """
    resp = client.post(
        "/documents",
        json={**sample_payload, "published_at": "not-a-date"},
    )
    assert resp.status_code == 422


def test_explicit_null_published_at_is_accepted(client, sample_payload):
    """Sending an explicit null is valid and means the same as omitting it.

    The crawler always sends the field, setting it to null when extraction
    failed, so this is the exact shape of a real "date not found" request.
    """
    resp = client.post(
        "/documents",
        json={**sample_payload, "published_at": None},
    )
    assert resp.status_code == 201
    assert resp.json()["published_at"] is None
