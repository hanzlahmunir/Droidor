"""Block detection: login walls, paywalls, bot challenges.

The false-positive tests matter as much as the detections. A classifier that
flags every article mentioning the word "subscribe" would quietly destroy the
corpus while looking like it was working.
"""

from app.pipeline.blocks import classify
from app.statuses import CrawlStatus

CLOUDFLARE_HTML = """
<html><head><title>Just a moment...</title></head>
<body><div id="cf-browser-verification">Checking your browser before accessing</div>
</body></html>
"""

CAPTCHA_HTML = """
<html><body><div class="g-recaptcha" data-sitekey="x"></div>
<p>Please verify you are a human</p></body></html>
"""

LOGIN_HTML = """
<html><body><h1>Sign in</h1>
<form><input type="email"><input type="password"></form>
<p>You must be logged in to view this content.</p></body></html>
"""

PAYWALL_JSON_LD = """
<html><head><script type="application/ld+json">
{"@type":"NewsArticle","headline":"X","isAccessibleForFree":false}
</script></head>
<body><p>The first paragraph is free to read, and then it stops right here.</p>
</body></html>
"""

PAYWALL_META = """
<html><head><meta property="article:content_tier" content="locked"></head>
<body><p>Teaser paragraph only.</p></body></html>
"""

JS_SHELL = """
<html><body><div id="root"></div>
<noscript>Please enable JavaScript to run this app.</noscript></body></html>
"""

CLEAN_ARTICLE = """
<html><body><article><h1>A normal post</h1>
<p>This is an ordinary blog article with a decent amount of text in it and no
walls of any kind, which should pass straight through the classifier.</p>
</article></body></html>
"""


def test_cloudflare_challenge_is_detected():
    verdict = classify(CLOUDFLARE_HTML, http_status=503, extracted_chars=50)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_captcha_is_detected():
    verdict = classify(CAPTCHA_HTML, http_status=200, extracted_chars=40)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_login_wall_is_detected():
    verdict = classify(LOGIN_HTML, http_status=200, extracted_chars=60)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.LOGIN_REQUIRED


def test_401_is_login_required():
    verdict = classify("<html><body>Nope</body></html>", http_status=401, extracted_chars=4)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.LOGIN_REQUIRED


def test_403_without_a_login_form_is_a_bot_wall_not_a_login():
    """403 and 401 mean different things, and conflating them mislabelled a run.

    Mozilla Hacks returned 403 to every request from the container while
    returning 200 for the same URL and User-Agent from the host machine.
    Nothing there needs a login -- the articles are public; the WAF was
    refusing a datacenter IP. Calling that "requires a login" would put a
    false statement in the data-quality report.
    """
    verdict = classify(
        "<html><body><h1>Access denied</h1></body></html>",
        http_status=403,
        extracted_chars=13,
    )
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_403_with_a_login_form_is_login_required():
    """More specific evidence wins: a 403 that actually shows a login form."""
    verdict = classify(LOGIN_HTML, http_status=403, extracted_chars=60)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.LOGIN_REQUIRED


def test_429_is_reported_as_a_bot_wall():
    """The remedy is the same as for a challenge: back off, do not retry harder."""
    verdict = classify("<html><body>slow down</body></html>", http_status=429, extracted_chars=9)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_json_ld_paywall_is_detected():
    """The most reliable paywall signal, because publishers must be truthful
    in schema.org markup or Google delists them."""
    verdict = classify(PAYWALL_JSON_LD, http_status=200, extracted_chars=70)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.PAYWALL_PARTIAL


def test_content_tier_meta_paywall_is_detected():
    verdict = classify(PAYWALL_META, http_status=200, extracted_chars=22)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.PAYWALL_PARTIAL


def test_paywall_is_distinct_from_login():
    """They are separate statuses because the failure modes differ.

    A paywall usually SHOWS a teaser, so extraction "succeeds" and produces a
    plausible short article. Merging the two would hide that.
    """
    paywall = classify(PAYWALL_JSON_LD, http_status=200, extracted_chars=70)
    login = classify(LOGIN_HTML, http_status=200, extracted_chars=60)
    assert paywall.status is not login.status


def test_js_only_shell_is_detected():
    verdict = classify(JS_SHELL, http_status=200, extracted_chars=45)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_clean_article_passes():
    assert not classify(CLEAN_ARTICLE, http_status=200, extracted_chars=150).blocked


# ---- false positives: the tests that stop the classifier eating the corpus ----

def test_article_about_paywalls_is_not_flagged():
    """A long article discussing paywalls legitimately contains the phrases.

    This is why the prose checks are gated on the page having little content.
    Without that gate, any piece about publishing economics would be dropped.
    """
    html = (
        "<html><body><article><h1>The economics of paywalls</h1>"
        + "<p>Publishers often ask readers to subscribe to continue reading, "
        "and this article examines whether that model works. </p>" * 12
        + "</article></body></html>"
    )
    assert not classify(html, http_status=200, extracted_chars=4000).blocked


def test_sidebar_login_form_on_a_real_article_is_not_flagged():
    """WordPress ships a login form in the sidebar by default.

    A password field alone must not condemn an article -- only a password
    field on a page with almost no content.
    """
    html = (
        "<html><body>"
        '<aside><form><input type="password"></form></aside>'
        "<article>" + "<p>Real article content goes here in some volume. </p>" * 30
        + "</article></body></html>"
    )
    assert not classify(html, http_status=200, extracted_chars=5000).blocked


def test_empty_html_is_not_blocked():
    """Empty input is an extraction problem, not a wall. Different status."""
    assert not classify("", http_status=200, extracted_chars=0).blocked


# ---------------------------------------------------------------------------
# Regression: the Cloudflare telemetry false positive.
#
# On the first live run every Mozilla Hacks article was discarded as a bot
# wall. The pages were normal 200 responses of ~43 KB; the string
# "cdn-cgi/challenge-platform" appeared near the end inside Cloudflare's
# passive telemetry beacon (window.__CF$cv$params), which Cloudflare injects
# into EVERY page it serves. The match detected "this site uses Cloudflare",
# not "Cloudflare is blocking you".
#
# The snippet below is the real beacon from that page.
# ---------------------------------------------------------------------------

CLOUDFLARE_TELEMETRY_ON_A_REAL_ARTICLE = (
    "<html><body><article>"
    + "<p>This is a genuine article served through Cloudflare, with several "
    "paragraphs of real content that the extractor handles perfectly well. </p>" * 20
    + "</article>"
    + """<script>window.__CF$cv$params={r:'a233fd67cd252490',t:'MTc4NTQxMDU5MQ=='};
    var a=document.createElement('script');
    a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script>"""
    + "</body></html>"
)


def test_cloudflare_telemetry_on_a_real_article_is_not_a_wall():
    """A 200 page full of article text is not blocked, whatever its scripts say."""
    verdict = classify(
        CLOUDFLARE_TELEMETRY_ON_A_REAL_ARTICLE, http_status=200, extracted_chars=2800
    )
    assert not verdict.blocked, (
        f"false positive: a real article was classified as {verdict.status} "
        f"because of {verdict.detail}"
    )


def test_a_genuine_challenge_is_still_caught():
    """The fix must not disarm the detector.

    A real interstitial is small and has almost no text, so it still trips
    every check.
    """
    verdict = classify(CLOUDFLARE_HTML, http_status=503, extracted_chars=45)
    assert verdict.blocked
    assert verdict.status is CrawlStatus.BOT_WALL


def test_marker_on_an_error_status_is_still_a_wall():
    """Length alone must not excuse a 403.

    A verbose block page could exceed the text threshold; the non-success
    status is what keeps it classified correctly.
    """
    html = CLOUDFLARE_HTML + "<p>" + ("padding text " * 400) + "</p>"
    verdict = classify(html, http_status=403, extracted_chars=5000)
    assert verdict.blocked


def test_bot_wall_is_checked_before_login():
    """Order matters: challenge pages often return 403 AND contain a form.

    If the login check ran first, every Cloudflare challenge would be
    misfiled as "requires login" and the report would be wrong about why
    pages were lost.
    """
    html = CLOUDFLARE_HTML.replace("</body>", '<input type="password"></body>')
    verdict = classify(html, http_status=403, extracted_chars=50)
    assert verdict.status is CrawlStatus.BOT_WALL
