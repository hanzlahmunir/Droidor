"""RSS/Atom feed expansion.

A feed is not a separate pipeline: it is a way of PRODUCING URLs, each of
which then goes through the identical single-URL path. That keeps one code
path for crawling, so a fix to extraction or dedupe applies to both modes
automatically.

Feeds carry one thing a bare URL does not -- the publisher's own structured
publish date. That is passed through as `feed_date` and sits at the top of
the date ladder, because it is the most authoritative source available.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import feedparser
import httpx

from app.config import Config

# Retry policy, tuned against observed behaviour rather than guessed.
#
# The first live run lost three of five feeds to "No address associated with
# hostname". A 3-attempt retry with 1s/2s backoff did NOT fix it -- the
# second run lost three feeds again. Measuring showed why: resolution
# succeeds 10/10 once the container has settled, so the failures are not
# random, they are BURSTY and clustered at container start, which is exactly
# when `seed` fires all five feed requests at once.
#
# So the feed retry is deliberately more patient than the article retry: more
# attempts, and a backoff long enough to outlast the startup window. A feed
# failure is also far more expensive than an article failure -- it loses
# every article behind it -- which justifies waiting longer here.
_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
_MAX_ATTEMPTS = 5
# 2s, 4s, 8s, 16s -> up to 30s of patience before giving up on a feed.
_BACKOFF_BASE_SECONDS = 2.0


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str | None
    published_raw: str | None
    """The feed's own date string, unparsed. Handed to the date ladder as the
    'rss' strategy rather than parsed here, so all date parsing and all
    sanity checking happen in exactly one place."""


@dataclass(frozen=True)
class FeedResult:
    ok: bool
    feed_title: str | None = None
    entries: tuple[FeedEntry, ...] = ()
    error: str | None = None


def fetch_feed(
    feed_url: str,
    config: Config,
    client: httpx.Client,
    limit: int | None = None,
) -> FeedResult:
    """Fetch and parse one feed into entries.

    Fetched with our own httpx client rather than letting feedparser do the
    download, so the feed request carries the same User-Agent and timeout as
    every other request we make. feedparser's built-in fetching would bypass
    all of that and identify us differently.
    """
    response = None
    last_error: str | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = client.get(feed_url, timeout=config.request_timeout_seconds)
            response.raise_for_status()
            break
        except _RETRYABLE as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            response = None
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
        except httpx.HTTPError as exc:
            # An HTTP error status is not transient -- do not retry it.
            return FeedResult(ok=False, error=f"could not fetch feed: {exc}")

    if response is None:
        return FeedResult(
            ok=False,
            error=f"could not fetch feed after {_MAX_ATTEMPTS} attempts: {last_error}",
        )

    # response.content (bytes), not .text: feedparser reads the XML
    # declaration to determine the encoding, and handing it a pre-decoded
    # string breaks that for any feed that is not UTF-8.
    parsed = feedparser.parse(response.content)

    # `bozo` means the XML was malformed. NOT treated as fatal: feedparser is
    # deliberately lenient and usually recovers a usable entry list from a
    # feed with, say, an unescaped ampersand. Only an empty result is fatal.
    if not parsed.entries:
        reason = ""
        if getattr(parsed, "bozo", 0) and getattr(parsed, "bozo_exception", None):
            reason = f" ({parsed.bozo_exception})"
        return FeedResult(ok=False, error=f"feed contained no entries{reason}")

    feed_title = None
    if getattr(parsed, "feed", None):
        feed_title = (parsed.feed.get("title") or "").strip() or None

    entries: list[FeedEntry] = []
    for item in parsed.entries:
        link = (item.get("link") or "").strip()
        if not link:
            # An entry with no link cannot be crawled. Skipped here rather
            # than sent into the pipeline to fail as INVALID_URL, because it
            # is a defect in the feed, not a URL we were asked to crawl.
            continue

        # Feeds disagree on which field holds the date; try both standard
        # spellings before giving up. The raw string is passed on unparsed.
        published = (
            item.get("published")
            or item.get("updated")
            or item.get("created")
            or None
        )

        entries.append(
            FeedEntry(
                url=link,
                title=(item.get("title") or "").strip() or None,
                published_raw=published,
            )
        )
        if limit is not None and len(entries) >= limit:
            break

    return FeedResult(ok=True, feed_title=feed_title, entries=tuple(entries))
