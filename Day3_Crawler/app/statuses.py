"""The one vocabulary for "what happened to this URL".

Every URL that enters the pipeline leaves it with exactly one CrawlStatus.
That single rule is what makes the data-quality report trustworthy: the
percentages are counts over a partition of the input, so they sum to 100%
and nothing can be silently dropped on the floor.

The alternative -- ad-hoc strings written at each failure site -- is how you
end up with "failed", "FAILED" and "error" as three different buckets and a
report that quietly under-counts.

An enum rather than plain strings so a typo is an AttributeError at import
time instead of a wrong number in the report.
"""

from enum import Enum


class CrawlStatus(str, Enum):
    """Terminal outcome for one URL.

    Inherits from str so it serialises straight to JSON and compares to
    database values without conversion.
    """

    # ---------- success ----------
    STORED = "stored"
    """Extracted cleanly, passed every quality gate, accepted by the API."""

    # ---------- refused before we ever fetched ----------
    # These matter to report separately from failures: not fetching because
    # we were told not to is correct behaviour, not a defect in the crawler.

    INVALID_URL = "invalid_url"
    """Could not be repaired into a syntactically valid, resolvable URL."""

    ROBOTS_DISALLOWED = "robots_disallowed"
    """robots.txt forbids this path for our user-agent. We never requested it."""

    RATE_LIMITED = "rate_limited"
    """Our own hourly/daily/monthly budget was exhausted. Self-imposed."""

    # ---------- fetched, but the site would not give us the article ----------

    LOGIN_REQUIRED = "login_required"
    """Content sits behind authentication.

    The task is explicit that nothing behind a login is in scope, so this is
    detected and reported, never worked around.
    """

    PAYWALL_PARTIAL = "paywall_partial"
    """A teaser is visible but the article is metered/locked.

    Split out from LOGIN_REQUIRED because it is the more dangerous case: it
    extracts "successfully" and yields a plausible-looking two-paragraph
    document. Without this status those land in the database as real
    articles and quietly poison the corpus.
    """

    BOT_WALL = "bot_wall"
    """A challenge page: Cloudflare/Akamai/DataDome interstitial, JS challenge,
    or CAPTCHA. Detected and reported. We do not attempt to defeat it."""

    FETCH_FAILED = "fetch_failed"
    """Network-level failure: DNS, timeout, connection reset, 5xx, or a
    non-HTML content type."""

    # ---------- fetched fine, but the content was not usable ----------

    EXTRACTION_FAILED = "extraction_failed"
    """The page was retrieved but no article-shaped text came out of it.

    Distinct from JUNK: here the extractors returned essentially nothing.
    """

    JUNK = "junk"
    """Text was extracted but failed a quality rule -- too short, too
    link-dense, or the two extractors disagreed sharply.

    The rule that fired is recorded alongside, so "% junk" can be broken down
    by cause instead of being one opaque number.
    """

    # ---------- fine, but we already have it ----------

    DUPLICATE_URL = "duplicate_url"
    """Normalises to a URL we have already crawled."""

    DUPLICATE_CONTENT = "duplicate_content"
    """Byte-identical article text (same SHA-256) under a different URL.
    Typical of syndication and of one post served at two paths."""

    DUPLICATE_NEAR = "duplicate_near"
    """Not identical, but above the similarity threshold -- a repost with a
    changed intro, or the same piece lightly edited."""

    # ---------- the API rejected it ----------

    API_REJECTED = "api_rejected"
    """Day 1 returned 4xx other than 409 (which is DUPLICATE_URL above).
    In practice a 422: our payload violated the API's contract. Recorded
    rather than swallowed, because it means the crawler produced something
    malformed and that is a bug worth seeing."""


# Groupings used by the report. Defined here, next to the enum, so a new
# status cannot be added without deciding which bucket it belongs to.

SUCCESS_STATUSES = frozenset({CrawlStatus.STORED})

DUPLICATE_STATUSES = frozenset({
    CrawlStatus.DUPLICATE_URL,
    CrawlStatus.DUPLICATE_CONTENT,
    CrawlStatus.DUPLICATE_NEAR,
})

BLOCKED_STATUSES = frozenset({
    CrawlStatus.LOGIN_REQUIRED,
    CrawlStatus.PAYWALL_PARTIAL,
    CrawlStatus.BOT_WALL,
})

# "Extraction failed or returned junk" -- the exact phrase in the task.
EXTRACTION_FAILURE_STATUSES = frozenset({
    CrawlStatus.EXTRACTION_FAILED,
    CrawlStatus.JUNK,
})

REFUSED_BEFORE_FETCH_STATUSES = frozenset({
    CrawlStatus.INVALID_URL,
    CrawlStatus.ROBOTS_DISALLOWED,
    CrawlStatus.RATE_LIMITED,
})


# Human-readable messages. The UI shows these verbatim, so a user who pastes
# a URL of a login-walled site gets an explanation rather than a bare code.
STATUS_MESSAGES: dict[CrawlStatus, str] = {
    CrawlStatus.STORED: "Stored successfully.",
    CrawlStatus.INVALID_URL: "Not a valid URL, even after attempting repair.",
    CrawlStatus.ROBOTS_DISALLOWED: "Skipped: robots.txt disallows crawling this page.",
    CrawlStatus.RATE_LIMITED: "Skipped: rate limit reached. Try again later.",
    CrawlStatus.LOGIN_REQUIRED: "Cannot scrape: this page requires a login.",
    CrawlStatus.PAYWALL_PARTIAL: "Cannot scrape: article is behind a paywall (only a teaser is public).",
    CrawlStatus.BOT_WALL: "Cannot scrape: the site is behind a bot check or CAPTCHA.",
    CrawlStatus.FETCH_FAILED: "Could not fetch the page.",
    CrawlStatus.EXTRACTION_FAILED: "Fetched the page, but found no article text in it.",
    CrawlStatus.JUNK: "Extracted text failed the quality checks.",
    CrawlStatus.DUPLICATE_URL: "Already crawled: this URL is already stored.",
    CrawlStatus.DUPLICATE_CONTENT: "Already stored under a different URL (identical text).",
    CrawlStatus.DUPLICATE_NEAR: "Near-duplicate of an article already stored.",
    CrawlStatus.API_REJECTED: "The documents API rejected this document.",
}


def message_for(status: CrawlStatus, detail: str | None = None) -> str:
    """Human-readable explanation, optionally with a specific reason appended.

    `detail` carries the specific cause -- which junk rule fired, which HTTP
    code came back -- so the UI can show "failed the quality checks (too
    short: 84 chars, minimum 300)" rather than only the generic sentence.
    """
    base = STATUS_MESSAGES.get(status, str(status))
    return f"{base} ({detail})" if detail else base
