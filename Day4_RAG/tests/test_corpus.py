"""Tests for loading the corpus from the Documents API.

respx mocks httpx at the transport layer, so these run with zero network
access and are deterministic in CI -- the same approach Day 3 used for its
fetcher tests.
"""

import httpx
import pytest
import respx

from app.config import Config
from app.corpus import CorpusError, load_articles

API = "http://api:8000"


def make_config() -> Config:
    import os

    os.environ["API_BASE_URL"] = API
    return Config()


def document(doc_id: int, **overrides) -> dict:
    row = {
        "id": doc_id,
        "title": f"Article {doc_id}",
        "url": f"https://example.com/{doc_id}",
        "text": f"Body text for article {doc_id}, long enough to be real.",
        "source": "example.com",
        "published_at": None,
    }
    row.update(overrides)
    return row


@respx.mock
def test_loads_a_single_page():
    respx.get(f"{API}/documents").mock(
        return_value=httpx.Response(200, json=[document(1), document(2)])
    )
    articles = load_articles(make_config())
    assert [a.id for a in articles] == [1, 2]
    assert articles[0].title == "Article 1"


@respx.mock
def test_follows_pagination_past_the_first_page():
    # THE TRAP THIS GUARDS. Day 1 caps limit at 100. Assuming one request is
    # the whole corpus works fine at 20 articles and silently truncates at
    # 101 -- the failure appears much later, as questions that cannot be
    # answered from articles that were never indexed.
    config = make_config()
    page_size = config.corpus_page_size

    first = [document(i) for i in range(page_size)]
    second = [document(page_size + i) for i in range(5)]

    route = respx.get(f"{API}/documents")
    route.side_effect = [
        httpx.Response(200, json=first),
        httpx.Response(200, json=second),
    ]

    articles = load_articles(config)
    assert len(articles) == page_size + 5
    assert route.call_count == 2

    # The second request must actually advance the offset.
    assert route.calls[1].request.url.params["offset"] == str(page_size)


@respx.mock
def test_stops_on_a_short_page_without_an_extra_request():
    config = make_config()
    route = respx.get(f"{API}/documents").mock(
        return_value=httpx.Response(200, json=[document(1)])
    )
    load_articles(config)
    assert route.call_count == 1


@respx.mock
def test_articles_with_empty_text_are_skipped():
    # Counting a text-less article as ingested would inflate the numbers while
    # contributing nothing retrievable.
    respx.get(f"{API}/documents").mock(
        return_value=httpx.Response(
            200, json=[document(1), document(2, text="   "), document(3, text="")]
        )
    )
    articles = load_articles(make_config())
    assert [a.id for a in articles] == [1]


@respx.mock
def test_unreachable_api_gives_an_actionable_error():
    respx.get(f"{API}/documents").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(CorpusError) as exc:
        load_articles(make_config())
    # The message must say what to DO, not just what failed.
    assert "docker compose up" in str(exc.value)


@respx.mock
def test_http_error_status_is_reported_with_its_code():
    respx.get(f"{API}/documents").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(CorpusError) as exc:
        load_articles(make_config())
    assert "500" in str(exc.value)


@respx.mock
def test_a_changed_response_schema_names_the_missing_field():
    # If Day 1's schema changes, the error should point straight at it rather
    # than surfacing as a KeyError from somewhere deeper.
    broken = document(1)
    del broken["url"]
    respx.get(f"{API}/documents").mock(return_value=httpx.Response(200, json=[broken]))

    with pytest.raises(CorpusError) as exc:
        load_articles(make_config())
    assert "url" in str(exc.value)


@respx.mock
def test_non_list_response_is_rejected():
    respx.get(f"{API}/documents").mock(
        return_value=httpx.Response(200, json={"detail": "nope"})
    )
    with pytest.raises(CorpusError):
        load_articles(make_config())
