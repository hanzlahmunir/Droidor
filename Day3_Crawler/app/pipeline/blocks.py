"""Detecting pages we are not allowed to read: logins, paywalls, bot walls.

WHY THIS IS A FEATURE AND NOT AN ERROR HANDLER.
Without it, a login wall or a Cloudflare challenge still "extracts
successfully" -- into a 200-character document saying "Please enable
JavaScript" or "Sign in to continue". Those land in the database as articles.
They are the exact garbage the task predicts will show up among the shortest
documents. Detecting them explicitly does two things: it keeps the corpus
clean, and it turns "% extraction failed" into a breakdown with causes rather
than one opaque number.

WE DETECT, WE DO NOT DEFEAT.
The task says nothing behind a login. So a detected wall ends that URL with a
status and a human-readable message. There is no bypass, no cookie injection,
no CAPTCHA solving. That is a deliberate boundary, not a missing feature.

ORDER OF CHECKS MATTERS. A Cloudflare challenge often returns 403 with a page
containing a form -- so bot-wall detection runs before login detection, or
every challenge would be misfiled as "requires login".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.statuses import CrawlStatus

# ---------------------------------------------------------------------------
# Bot-wall / challenge fingerprints.
#
# Matched against the raw HTML, case-insensitively. These are strings the
# vendors put in their own interstitials; they do not appear in normal
# articles. Kept as a visible list rather than a clever heuristic so a
# reviewer can see exactly what is being matched and add to it.
# ---------------------------------------------------------------------------
_BOT_WALL_MARKERS = (
    # Cloudflare.
    #
    # NOTE what is NOT in this list: "cdn-cgi/challenge-platform" and
    # "ray id:". Both were here originally and both produced FALSE POSITIVES
    # on the first live run -- every Mozilla Hacks article was thrown away as
    # a bot wall.
    #
    # Cause, established by fetching one of those pages directly: it returns
    # HTTP 200 with a normal 43 KB article, and the string
    # "cdn-cgi/challenge-platform" appears at offset 43059 inside Cloudflare's
    # passive telemetry beacon (window.__CF$cv$params). Cloudflare injects
    # that script into EVERY page it serves, challenge or not. Matching it
    # detects "this site uses Cloudflare", which is a large fraction of the
    # web, rather than "Cloudflare is blocking you".
    #
    # "ray id:" is the same mistake: it appears in Cloudflare's ordinary
    # footer and error pages alike.
    #
    # What remains below are strings that appear ONLY on an actual interstitial.
    "cf-browser-verification",
    "cf_chl_opt",
    "cf-challenge-running",
    "checking your browser before accessing",
    "attention required! | cloudflare",
    "just a moment...",
    "enable javascript and cookies to continue",
    # Akamai
    "reference #18.",
    "access denied | akamai",
    # DataDome / PerimeterX / Imperva
    "datadome",
    "px-captcha",
    "perimeterx",
    "incapsula incident id",
    "_incapsula_resource",
    # Generic CAPTCHA
    "g-recaptcha",
    "grecaptcha.render",
    "hcaptcha.com/captcha",
    "captcha-delivery.com",
    "please verify you are a human",
    "are you a robot",
    "unusual traffic from your computer network",
)

# ---------------------------------------------------------------------------
# Login / authentication markers.
# ---------------------------------------------------------------------------
_LOGIN_TEXT_MARKERS = (
    "sign in to continue",
    "log in to continue",
    "please sign in to read",
    "please log in to view",
    "you must be logged in",
    "members only",
    "subscribers only",
    "this content is for members",
    "create a free account to read",
    "sign up to read the full",
    "register to continue reading",
)

# ---------------------------------------------------------------------------
# Paywall markers. Separate from login because the failure mode differs: a
# paywall usually SHOWS a teaser, so extraction succeeds and yields a
# plausible-looking short article. That is the dangerous case.
# ---------------------------------------------------------------------------
_PAYWALL_TEXT_MARKERS = (
    "subscribe to continue reading",
    "subscribe to read",
    "this article is for subscribers",
    "you've reached your article limit",
    "you have reached your free article",
    "your free trial has ended",
    "start your free trial to read",
    "unlock this article",
    "premium content",
    "paid subscribers only",
)

# Machine-readable paywall signals. Far more reliable than prose matching,
# because publishers emit these for Google's benefit and must be truthful:
# lying in schema.org markup gets a site delisted from Google News.
_PAYWALL_META_PATTERNS = (
    # <meta property="article:content_tier" content="locked">
    re.compile(r'article:content_tier["\'\s]*content=["\'](locked|metered)', re.I),
    # Google's paywall signal
    re.compile(r'"isAccessibleForFree"\s*:\s*(false|"false")', re.I),
    re.compile(r'isAccessibleForFree["\'\s]*content=["\']?false', re.I),
)


@dataclass(frozen=True)
class BlockVerdict:
    """Result of the block checks. `blocked=False` means carry on extracting."""

    blocked: bool
    status: CrawlStatus | None = None
    detail: str | None = None


# A challenge page is small and has almost no readable text -- its whole job
# is to run JavaScript and redirect. A page that served a real article did
# not block us, whatever strings happen to appear in its analytics scripts.
_REAL_ARTICLE_CHARS = 1200


def _looks_like_a_real_article(extracted_chars: int, http_status: int | None) -> bool:
    """Structural veto over marker matching.

    THE GENERAL LESSON, learned the expensive way: a substring match against
    a whole HTML document is evidence, not proof. Vendor scripts, footers and
    analytics beacons carry vendor strings on perfectly normal pages.

    So a marker only counts when the page ALSO behaves like a wall: a
    non-success status, or almost no article text. A 200 response carrying
    1,200+ characters of extracted prose is an article -- the crawler already
    got what it came for, so calling it "blocked" is self-evidently wrong.

    This is the guard that stops one over-broad marker silently deleting
    every article on a large slice of the web, which is exactly what
    happened before it existed.
    """
    if http_status is not None and http_status >= 400:
        return False
    return extracted_chars >= _REAL_ARTICLE_CHARS


def _find_marker(haystack: str, markers: tuple[str, ...]) -> str | None:
    """Return the first marker present in `haystack`, or None.

    Returns the marker itself rather than a boolean so the crawl record can
    say WHICH signal fired. "bot wall (matched: cf-browser-verification)" is
    debuggable; "bot wall" is not.
    """
    for marker in markers:
        if marker in haystack:
            return marker
    return None


def _has_login_form(soup: BeautifulSoup) -> bool:
    """True if the page contains a password input.

    A password field is a strong, structural signal -- far better than text
    matching, which trips on any article that merely discusses logging in.

    The refinement that matters: many normal blogs have a login form in a
    sidebar or footer (WordPress does by default). So a password field alone
    is NOT enough; the caller only consults this when the page also has
    little or no article content.
    """
    return soup.find("input", attrs={"type": "password"}) is not None


def _json_ld_says_paid(soup: BeautifulSoup) -> bool:
    """Check schema.org JSON-LD for an explicit not-free flag.

    Wrapped in a broad try/except: JSON-LD in the wild is frequently invalid
    JSON, contains comments, or is an array of mixed types. A malformed block
    must not crash the crawl -- it just means this signal is unavailable.
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            value = item.get("isAccessibleForFree")
            # Publishers emit this as a bool, "False", or "false".
            if value is False or (isinstance(value, str) and value.lower() == "false"):
                return True
    return False


def classify(
    html: str,
    *,
    http_status: int | None,
    extracted_chars: int,
) -> BlockVerdict:
    """Decide whether this page is a wall rather than an article.

    `extracted_chars` is passed in because several checks are only meaningful
    in combination with how much text came out. A password field on a page
    with 8,000 characters of article is a sidebar widget; the same field on a
    page with 200 characters is the entire content.
    """
    if not html:
        return BlockVerdict(blocked=False)

    lowered = html.lower()
    soup = BeautifulSoup(html, "lxml")

    # ---- 1. Bot walls FIRST ----
    # Runs before the login check because challenge pages routinely return
    # 403 and contain form elements; checking login first would misfile them.
    marker = _find_marker(lowered, _BOT_WALL_MARKERS)
    if marker is not None and not _looks_like_a_real_article(extracted_chars, http_status):
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.BOT_WALL,
            detail=f"matched bot-protection marker: {marker!r}",
        )

    # 429 is rate limiting by the site. Reported as a bot wall because the
    # remedy is identical -- back off, do not retry harder.
    if http_status == 429:
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.BOT_WALL,
            detail="HTTP 429: the site is rate-limiting us",
        )

    # ---- 2. Explicit machine-readable paywall signals ----
    # Checked before prose matching: these are structured, publisher-authored
    # declarations, so they are both more reliable and cheaper to justify.
    if _json_ld_says_paid(soup):
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.PAYWALL_PARTIAL,
            detail='JSON-LD declares "isAccessibleForFree": false',
        )

    for pattern in _PAYWALL_META_PATTERNS:
        if pattern.search(html):
            return BlockVerdict(
                blocked=True,
                status=CrawlStatus.PAYWALL_PARTIAL,
                detail=f"paywall metadata matched: {pattern.pattern[:40]}",
            )

    # ---- 3. HTTP status that means "not for you" ----
    if http_status == 401:
        # Unambiguous: 401 means the server is demanding credentials.
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.LOGIN_REQUIRED,
            detail="HTTP 401: the server requires authentication",
        )

    if http_status == 403:
        # 403 is NOT the same as 401, and conflating them produced a wrong
        # label in a real run. Mozilla Hacks returned 403 to every request
        # from the container while returning 200 to the identical URL and
        # identical User-Agent from the host machine. Nothing there requires
        # a login -- the articles are public. What differed was the egress IP:
        # the container leaves through a datacenter range that the site's WAF
        # declines to serve.
        #
        # Reporting that as "requires a login" would be a false statement in
        # the data-quality report, and would send anyone reading it looking
        # for credentials that do not exist. It is an anti-bot refusal, so it
        # belongs with the other bot walls.
        #
        # A 403 that came with an actual login form is caught by the
        # password-field check further down, which is more specific evidence
        # than the status code alone.
        if _has_login_form(soup) and extracted_chars < 500:
            return BlockVerdict(
                blocked=True,
                status=CrawlStatus.LOGIN_REQUIRED,
                detail="HTTP 403 with a login form: authentication required",
            )
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.BOT_WALL,
            detail=(
                "HTTP 403 with no login form: the site refused this client "
                "(commonly an IP-reputation or WAF block rather than an "
                "authentication requirement)"
            ),
        )

    # ---- 4. Prose markers, only when there is little real content ----
    # Gated on extracted_chars: an article ABOUT paywalls legitimately
    # contains the phrase "subscribe to continue reading". Requiring the page
    # to be mostly empty as well is what stops that false positive.
    if extracted_chars < 1500:
        marker = _find_marker(lowered, _LOGIN_TEXT_MARKERS)
        if marker is not None:
            return BlockVerdict(
                blocked=True,
                status=CrawlStatus.LOGIN_REQUIRED,
                detail=f"login-wall text with only {extracted_chars} chars extracted: {marker!r}",
            )

        marker = _find_marker(lowered, _PAYWALL_TEXT_MARKERS)
        if marker is not None:
            return BlockVerdict(
                blocked=True,
                status=CrawlStatus.PAYWALL_PARTIAL,
                detail=f"paywall text with only {extracted_chars} chars extracted: {marker!r}",
            )

    # ---- 5. Password field on an otherwise empty page ----
    if extracted_chars < 500 and _has_login_form(soup):
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.LOGIN_REQUIRED,
            detail=(
                f"page contains a password field and only {extracted_chars} "
                "chars of text"
            ),
        )

    # ---- 6. JS-only shells ----
    # A near-empty page that tells you to enable JavaScript is a client-
    # rendered site, not an article. Reported as a bot wall because the
    # practical consequence is the same: this fetcher cannot read it.
    if extracted_chars < 300 and (
        "please enable javascript" in lowered
        or "javascript is required" in lowered
        or "enable javascript to run this app" in lowered
    ):
        return BlockVerdict(
            blocked=True,
            status=CrawlStatus.BOT_WALL,
            detail="page requires JavaScript to render its content",
        )

    return BlockVerdict(blocked=False)
