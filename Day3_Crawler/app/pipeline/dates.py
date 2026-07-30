"""Publish-date extraction: a ladder of five strategies, most reliable first.

The task asks for "% with a missing or unparseable date". To make that number
mean anything, two things are required:

  1. A real effort to find the date, so a high miss rate reflects the web and
     not a lazy parser.
  2. A record of WHICH strategy succeeded, so the report can show where dates
     actually come from instead of reporting one bare percentage.

Hence `DateResult.source`. The report tabulates it, which is far more useful
than "83% had dates": it shows that (say) JSON-LD carried most of them and
visible text carried almost none, which tells you where to invest next.

WHY THIS ORDER. Strategies are tried from most to least authoritative:

  1. rss            the feed publisher's own structured date. Definitive.
  2. json_ld        schema.org datePublished. Machine-readable, and
                    publishers keep it correct because Google reads it.
  3. meta_article   OpenGraph/article:published_time. Same idea, flatter.
  4. time_element   <time datetime="...">. HTML's own semantic element.
  5. text_pattern   dates in visible prose. Last resort -- ambiguous
                    (03/04/2019 is two different days depending on locale)
                    and easily picks up a comment or "related post" date.

The first hit wins, so a page with both JSON-LD and a prose date uses the
structured one.

SANITY CHECKING IS PART OF PARSING. A "successfully parsed" 1970 or 2049 date
is worse than no date: it looks valid and silently corrupts any
sort-by-date. Implausible values are rejected and reported as unparseable,
with the raw string kept as evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from app.config import Config

# Attribute names carrying a publish date, in the order we trust them.
# Several sites emit more than one, occasionally disagreeing.
_META_DATE_KEYS = (
    "article:published_time",
    "og:article:published_time",
    "datePublished",
    "date",
    "pubdate",
    "publish-date",
    "publication_date",
    "DC.date.issued",
    "dc.date",
    "sailthru.date",
    "parsely-pub-date",
    # Last in the list because it is an UPDATE time, not a publish time, so
    # it is only used when nothing better exists. Added after measuring: with
    # the RSS hint removed, 8 of 20 cached pages reported no date at all, and
    # inspecting them showed most carried og:updated_time and nothing else.
    # An update time is an imperfect answer; no date is a worse one.
    "og:updated_time",
    "article:modified_time",
)

# Visible-text patterns, for the last-resort strategy.
_TEXT_DATE_PATTERNS = (
    # "March 14, 2019" / "Mar 14 2019"
    re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2}),?\s+(\d{4})\b",
        re.I,
    ),
    # "14 March 2019"
    re.compile(
        r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})\b",
        re.I,
    ),
    # ISO-ish "2019-03-14"
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)


@dataclass(frozen=True)
class DateResult:
    """Outcome of date extraction for one page."""

    value: datetime | None
    source: str | None
    """Which strategy produced it: rss / json_ld / meta_article /
    time_element / text_pattern. None when nothing was found."""
    raw: str | None
    """The unparsed string, kept even on failure -- it is the evidence for
    'unparseable' and shows what a future parser would need to handle."""
    error: str | None = None


def _validate(parsed: datetime, config: Config) -> tuple[datetime | None, str | None]:
    """Apply the plausibility window to an already-parsed datetime.

    Factored out so the epoch path and the dateutil path cannot drift apart --
    a date that skipped these checks would be stored looking perfectly valid.
    """
    # A date with no timezone is assumed UTC. Stated rather than silent: the
    # alternative is a naive datetime that compares wrongly against the aware
    # values everywhere else, and shifts by hours depending on where the
    # container runs.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    if parsed.year < config.min_plausible_year:
        # Almost always a Unix-epoch default (1970-01-01) written by a CMS
        # with an empty date field, or a mis-parsed page number.
        return None, f"implausible year {parsed.year} (before {config.min_plausible_year})"

    cutoff = datetime.now(timezone.utc) + timedelta(days=config.future_date_tolerance_days)
    if parsed > cutoff:
        # Usually a scheduled-post placeholder, or a mis-parsed day/month.
        return None, f"date is in the future ({parsed.date().isoformat()})"

    return parsed, None


def _parse_and_validate(raw: str, config: Config) -> tuple[datetime | None, str | None]:
    """Parse a date string and reject implausible results.

    Returns (datetime, None) on success or (None, reason) on failure.
    """
    if not raw or not raw.strip():
        return None, "empty date string"

    raw = raw.strip()

    # Unix epoch seconds, e.g. og:updated_time="1785359721".
    #
    # Handled explicitly because dateutil CANNOT: given a bare integer it
    # either fails or, worse, interprets the digits as a date and returns
    # something confidently wrong. Found by measurement -- with the RSS hint
    # removed, most of the pages reporting no date were emitting exactly this.
    #
    # The 10-13 digit bound distinguishes a timestamp from a year ("2019") or
    # a page number: 10 digits covers 2001-2286 in seconds, 13 in
    # milliseconds. Anything shorter is not a timestamp.
    if raw.isdigit() and 10 <= len(raw) <= 13:
        try:
            value = int(raw)
            # 13 digits means milliseconds, which some CMSes emit.
            if len(raw) == 13:
                value //= 1000
            return _validate(
                datetime.fromtimestamp(value, tz=timezone.utc), config
            )
        except (ValueError, OverflowError, OSError):
            return None, "unparseable epoch timestamp"

    try:
        # dateutil handles ISO-8601, RFC 822 (what RSS uses) and most prose
        # forms. Writing this by hand is a known tar pit.
        parsed = dateutil_parser.parse(raw)
    except (ValueError, OverflowError, TypeError) as exc:
        return None, f"unparseable ({type(exc).__name__})"

    return _validate(parsed, config)


def _from_json_ld(soup: BeautifulSoup) -> str | None:
    """schema.org datePublished from a JSON-LD block."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # Invalid JSON-LD is common. Skip this block, try the next.
            continue

        # A JSON-LD block may be a single object, a list, or an @graph
        # wrapper. Flatten all three rather than handling only the easy case.
        candidates: list = []
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                candidates.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    candidates.extend(g for g in graph if isinstance(g, dict))

        for item in candidates:
            for key in ("datePublished", "dateCreated", "uploadDate"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _from_meta(soup: BeautifulSoup) -> str | None:
    """<meta property="article:published_time" content="...">."""
    for key in _META_DATE_KEYS:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: key})
            if tag:
                content = (tag.get("content") or "").strip()
                if content:
                    return content
    return None


def _from_time_element(soup: BeautifulSoup) -> str | None:
    """<time datetime="2019-03-14">.

    Prefers a time element carrying a publish-ish class or itemprop, because
    a page often has several: published, updated, and one per comment. An
    unqualified <time> is used only as a fallback, and the FIRST one is taken
    on the assumption that the article's own date precedes its comments'.
    """
    qualified = soup.find(
        "time",
        attrs={"itemprop": re.compile(r"datePublished|dateCreated", re.I)},
    )
    if qualified is None:
        for tag in soup.find_all("time"):
            classes = " ".join(tag.get("class") or []).lower()
            if any(word in classes for word in ("publish", "post-date", "entry-date")):
                qualified = tag
                break

    tag = qualified or soup.find("time")
    if tag is None:
        return None

    value = (tag.get("datetime") or "").strip()
    return value or (tag.get_text(strip=True) or None)


def _from_text(soup: BeautifulSoup) -> str | None:
    """Last resort: a date in visible prose, from the top of the document.

    Only the first 3,000 characters are searched. Dates further down are
    overwhelmingly comment timestamps or "related posts", and matching those
    produces a confidently wrong answer -- worse than returning nothing.
    """
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)[:3000]
    for pattern in _TEXT_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def extract_date(
    html: str,
    config: Config,
    *,
    feed_date: str | None = None,
) -> DateResult:
    """Run the ladder and return the first plausible date.

    `feed_date` is the RSS entry's own published field, passed in when the
    URL came from a feed. It is tried first because the publisher stated it
    directly in structured form.
    """
    attempts: list[tuple[str, str | None]] = []

    if feed_date:
        attempts.append(("rss", feed_date))

    if html:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # noqa: BLE001
            soup = None

        if soup is not None:
            attempts.append(("json_ld", _from_json_ld(soup)))
            attempts.append(("meta_article", _from_meta(soup)))
            attempts.append(("time_element", _from_time_element(soup)))
            attempts.append(("text_pattern", _from_text(soup)))

    # Remember the first candidate we saw, even if every one fails to parse.
    # Reporting "found '14/03/19' but could not parse it" is actionable;
    # reporting "no date" when a string was clearly present is misleading.
    first_raw: str | None = None
    first_error: str | None = None

    for source, raw in attempts:
        if not raw:
            continue
        if first_raw is None:
            first_raw = raw

        parsed, error = _parse_and_validate(raw, config)
        if parsed is not None:
            return DateResult(value=parsed, source=source, raw=raw)

        if first_error is None:
            first_error = error

    if first_raw is not None:
        # Something date-shaped was found but nothing survived validation.
        return DateResult(value=None, source=None, raw=first_raw, error=first_error)

    return DateResult(value=None, source=None, raw=None, error="no date found on page")
