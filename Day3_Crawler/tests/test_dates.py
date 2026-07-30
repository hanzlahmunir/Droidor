"""Publish-date extraction: the ladder, and the sanity window.

The sanity checks get as much attention as the parsing, because a
confidently-wrong date is worse than no date: it looks valid, it sorts, and
nothing downstream flags it.
"""

import pytest

from app.pipeline.dates import extract_date

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@type": "BlogPosting", "headline": "X", "datePublished": "2019-03-14T09:30:00Z"}
</script>
</head><body><p>Body.</p></body></html>
"""

META_PAGE = """
<html><head>
<meta property="article:published_time" content="2020-06-01T12:00:00+02:00">
</head><body><p>Body.</p></body></html>
"""

TIME_ELEMENT_PAGE = """
<html><body>
<time datetime="2021-11-05">5 November 2021</time>
<p>Body.</p></body></html>
"""

TEXT_ONLY_PAGE = """
<html><body><div class="byline">Posted on March 14, 2019 by Someone</div>
<p>Body.</p></body></html>
"""

NO_DATE_PAGE = "<html><body><p>Just some text with no date anywhere.</p></body></html>"


def test_json_ld_is_found(config):
    result = extract_date(JSON_LD_PAGE, config)
    assert result.source == "json_ld"
    assert result.value.year == 2019
    assert result.value.month == 3


def test_meta_tag_is_found(config):
    result = extract_date(META_PAGE, config)
    assert result.source == "meta_article"
    assert result.value.year == 2020


def test_time_element_is_found(config):
    result = extract_date(TIME_ELEMENT_PAGE, config)
    assert result.source == "time_element"
    assert result.value.year == 2021


def test_visible_text_is_the_last_resort(config):
    result = extract_date(TEXT_ONLY_PAGE, config)
    assert result.source == "text_pattern"
    assert result.value.year == 2019


def test_no_date_is_reported_honestly(config):
    """No date must be None with a reason, never a silent default of 'now'."""
    result = extract_date(NO_DATE_PAGE, config)
    assert result.value is None
    assert result.source is None
    assert result.error


def test_feed_date_wins_over_page_markup(config):
    """The RSS date sits at the top of the ladder.

    The feed publisher stated it directly in structured form, so it beats
    anything scraped from the page body.
    """
    result = extract_date(JSON_LD_PAGE, config, feed_date="Mon, 01 Jan 2018 00:00:00 GMT")
    assert result.source == "rss"
    assert result.value.year == 2018


def test_naive_dates_are_treated_as_utc(config):
    """A date with no timezone must not become a naive datetime.

    A naive value compares wrongly against the aware datetimes used
    everywhere else, and shifts by hours depending on where the container is
    running.
    """
    page = '<html><head><meta name="date" content="2019-03-14 09:30:00"></head></html>'
    result = extract_date(page, config)
    assert result.value is not None
    assert result.value.tzinfo is not None


def test_timezone_is_converted_to_utc(config):
    """+02:00 12:00 is 10:00 UTC. Storing the local hour would be wrong."""
    result = extract_date(META_PAGE, config)
    assert result.value.hour == 10


# ---- the sanity window ----

def test_epoch_default_is_rejected(config):
    """1970-01-01 is a CMS with an empty date field, not a publish date."""
    page = '<html><head><meta name="date" content="1970-01-01T00:00:00Z"></head></html>'
    result = extract_date(page, config)
    assert result.value is None
    assert "implausible" in (result.error or "")
    # The raw string is kept: it is the evidence for "unparseable".
    assert result.raw == "1970-01-01T00:00:00Z"


def test_future_date_is_rejected(config):
    """Usually a scheduled-post placeholder or a mis-parsed day/month."""
    page = '<html><head><meta name="date" content="2099-01-01T00:00:00Z"></head></html>'
    result = extract_date(page, config)
    assert result.value is None
    assert "future" in (result.error or "")


def test_unparseable_string_keeps_the_raw_value(config):
    """'Missing' and 'found but unparseable' are different report lines.

    Keeping the raw string is what lets the report show WHAT a future parser
    would need to handle, rather than just counting a failure.
    """
    page = '<html><head><meta name="date" content="last Tuesday"></head></html>'
    result = extract_date(page, config)
    assert result.value is None
    assert result.raw == "last Tuesday"


def test_unix_epoch_timestamp_is_parsed(config):
    """Regression: og:updated_time is often a bare epoch integer.

    Found by measurement, not by guessing. Re-running the date ladder over
    the 20 cached pages with the RSS hint removed showed 8 producing no date
    at all; inspecting those showed most carried only
    `<meta property="og:updated_time" content="1785359721">`.

    dateutil cannot help here -- given a bare integer it either fails or,
    worse, reads the digits as a date and returns something confidently
    wrong. So the epoch case is detected before dateutil sees it.
    """
    page = '<html><head><meta property="og:updated_time" content="1785359721"></head></html>'
    result = extract_date(page, config)
    assert result.value is not None
    assert result.value.year == 2026
    assert result.value.tzinfo is not None


def test_epoch_milliseconds_are_parsed(config):
    """13 digits means milliseconds, which some CMSes emit."""
    page = '<html><head><meta name="date" content="1785359721000"></head></html>'
    result = extract_date(page, config)
    assert result.value is not None
    assert result.value.year == 2026


def test_a_bare_year_is_not_mistaken_for_a_timestamp(config):
    """The digit-length bound exists to stop "2019" becoming a timestamp.

    Without it, a four-digit year could be read as epoch seconds and land in
    1970 -- a confidently wrong date, which is worse than none.
    """
    page = '<html><head><meta name="date" content="2019"></head></html>'
    result = extract_date(page, config)
    # Either parsed sensibly as a year, or rejected -- but never 1970.
    if result.value is not None:
        assert result.value.year == 2019


def test_epoch_still_passes_through_the_sanity_window(config):
    """The epoch path must not bypass validation.

    Epoch 0 is 1970 and must be rejected exactly like any other implausible
    date -- which is why both paths share _validate().
    """
    page = '<html><head><meta name="date" content="0000000000"></head></html>'
    result = extract_date(page, config)
    assert result.value is None


def test_malformed_json_ld_does_not_crash(config):
    """Invalid JSON-LD is common in the wild and must not kill the crawl."""
    page = """
    <html><head><script type="application/ld+json">{not valid json,,,}</script>
    <meta property="article:published_time" content="2020-06-01T12:00:00Z">
    </head></html>
    """
    result = extract_date(page, config)
    # Falls through to the next rung of the ladder rather than raising.
    assert result.source == "meta_article"
    assert result.value.year == 2020


def test_empty_html_is_handled(config):
    result = extract_date("", config)
    assert result.value is None
