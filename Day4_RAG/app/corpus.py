"""Load the article corpus from the Day 1 Documents API.

WHY OVER HTTP RATHER THAN STRAIGHT FROM THE TABLE. The documents live in a
Postgres this process could connect to directly, and doing so would be fewer
moving parts. Going through the API is deliberate, for the reason Day 3 gave
when it POSTed instead of INSERTing: reaching around the API forks the
definition of "a document". The API decides what fields a document has, how
they are ordered and what pagination means. A second reader with its own SQL
would drift from that silently, and would keep working while the API's
contract broke.

PAGINATION IS NOT OPTIONAL HERE. Day 1 caps `limit` at 100 (le=100) and
returns rows ordered by id. A single request with limit=1000 does not fail
loudly -- FastAPI rejects it with a 422, which is fine -- but the subtler trap
is assuming one page is the whole corpus. This pages until a short page comes
back, so growing the corpus past 100 articles cannot silently truncate it.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Config


@dataclass(frozen=True)
class Article:
    """One stored article, as the API describes it."""

    id: int
    title: str
    url: str
    text: str
    source: str
    published_at: str | None = None


class CorpusError(RuntimeError):
    """The corpus could not be loaded.

    Raised with an actionable message rather than letting an httpx error
    surface raw: "connection refused to http://api:8000" is a fact, but "the
    Documents API is not reachable -- is `docker compose up` running?" is the
    fact plus what to do about it.
    """


def load_articles(config: Config, *, client: httpx.Client | None = None) -> list[Article]:
    """Fetch every article from the Documents API, following pagination.

    `client` is injectable so tests can supply a mocked transport and run with
    no network at all.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=config.request_timeout_seconds)

    articles: list[Article] = []
    offset = 0

    try:
        while True:
            try:
                response = client.get(
                    f"{config.api_base_url}/documents",
                    params={"limit": config.corpus_page_size, "offset": offset},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CorpusError(
                    f"The Documents API returned {exc.response.status_code} for "
                    f"{exc.request.url}. Body: {exc.response.text[:200]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise CorpusError(
                    f"Could not reach the Documents API at {config.api_base_url}: "
                    f"{exc}. Is the stack running? Try: docker compose up -d"
                ) from exc

            page = response.json()
            if not isinstance(page, list):
                raise CorpusError(
                    f"Expected a JSON list from /documents, got {type(page).__name__}."
                )

            for row in page:
                article = _to_article(row)
                # An article with no text is not an error -- but it cannot be
                # chunked, and counting it as ingested would inflate the
                # numbers. Skipped here so the ingest report can state the
                # difference between "20 articles" and "20 articles with text".
                if article.text.strip():
                    articles.append(article)

            # A short page means the end. Checking this rather than comparing
            # against a total means no extra endpoint is needed and no count
            # can go stale between requests.
            if len(page) < config.corpus_page_size:
                break
            offset += config.corpus_page_size

            # A hard stop. If the API ever returned full pages forever -- a
            # broken offset, a proxy replaying a response -- this loop would
            # otherwise run until memory ran out. Better to fail with a
            # diagnosis than to hang.
            if offset > 100_000:
                raise CorpusError(
                    "Pagination did not terminate after 100,000 rows. The API "
                    "may be ignoring `offset`."
                )
    finally:
        if owns_client:
            client.close()

    return articles


def _to_article(row: dict) -> Article:
    """Convert one API row, failing clearly if the contract has changed.

    A KeyError here means Day 1's response schema changed. Naming the missing
    field is the difference between a five-second fix and a debugging session.
    """
    missing = [k for k in ("id", "title", "url", "text", "source") if k not in row]
    if missing:
        raise CorpusError(
            f"A document from the API is missing required field(s) "
            f"{', '.join(missing)}. The Day 1 response schema may have changed. "
            f"Got keys: {sorted(row)}"
        )

    return Article(
        id=int(row["id"]),
        title=str(row["title"]),
        url=str(row["url"]),
        text=str(row["text"]),
        source=str(row["source"]),
        published_at=row.get("published_at"),
    )
