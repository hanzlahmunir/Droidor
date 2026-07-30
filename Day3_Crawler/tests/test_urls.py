"""URL repair, normalisation and the SSRF guard.

Table-driven: normalisation is a pile of small rules, and a table makes it
obvious which case is missing. Each case documents the rule it exercises.
"""

import pytest

from app.pipeline.urls import (
    BlockedURL,
    InvalidURL,
    assert_public_address,
    repair_and_normalise,
)


# (input, expected canonical, what rule this proves)
REPAIR_CASES = [
    ("example.com/post", "https://example.com/post", "adds a missing scheme"),
    ("example.com/post/", "https://example.com/post", "strips a trailing slash"),
    ("http://example.com/post", "https://example.com/post", "upgrades http to https"),
    ("HTTPS://Example.COM/Post", "https://example.com/Post", "lowercases host, keeps path case"),
    ("https://example.com/post#intro", "https://example.com/post", "drops an anchor fragment"),
    ("https://example.com//a//b/", "https://example.com/a/b", "collapses duplicate slashes"),
    ("https://example.com:443/x", "https://example.com/x", "removes the default port"),
    ("//example.com/x", "https://example.com/x", "handles protocol-relative URLs"),
    ("  https://example.com/x  ", "https://example.com/x", "trims whitespace"),
    ("<https://example.com/x>.", "https://example.com/x", "unwraps markdown punctuation"),
    ("https://example.com./x", "https://example.com/x", "removes a trailing dot in the host"),
]


@pytest.mark.parametrize("raw,expected,rule", REPAIR_CASES)
def test_repair(raw, expected, rule):
    assert repair_and_normalise(raw).canonical == expected, f"failed rule: {rule}"


def test_path_case_is_preserved():
    """Hostnames are case-insensitive; paths are NOT.

    Lowercasing the path would 404 on any case-sensitive server, which is
    most Unix-backed sites. This is the bug the rule exists to prevent.
    """
    assert repair_and_normalise("https://EXAMPLE.com/MyPost").canonical == (
        "https://example.com/MyPost"
    )


def test_tracking_parameters_are_stripped():
    result = repair_and_normalise(
        "https://example.com/p?utm_source=tw&utm_campaign=x&fbclid=abc"
    )
    assert result.canonical == "https://example.com/p"


def test_content_parameters_are_kept():
    """The over-aggressive-normalisation bug, guarded.

    "?p=123" IS the article on WordPress. Stripping every query parameter
    would turn every URL on such a site into the homepage, and the crawler
    would then dedupe them all into one document.
    """
    assert repair_and_normalise("https://example.com/?p=123").canonical == (
        "https://example.com/?p=123"
    )


def test_tracking_stripped_but_content_kept_together():
    result = repair_and_normalise("https://example.com/x?id=9&utm_source=tw&page=2")
    assert "id=9" in result.canonical
    assert "page=2" in result.canonical
    assert "utm_source" not in result.canonical


def test_hashbang_route_is_preserved():
    """A bare #anchor is a scroll target, but #!/path is a route.

    Dropping a hashbang would collapse every article on such a site to one
    URL -- and then the duplicate layer would merge them all.
    """
    assert repair_and_normalise("https://example.com/app#!/2019/post").canonical == (
        "https://example.com/app#!/2019/post"
    )


def test_variants_of_one_article_normalise_identically():
    """The property the whole module exists for.

    All five spellings are the same article, so they must produce one
    canonical key -- otherwise the duplicate check never fires and Day 1's
    unique constraint stores five copies.
    """
    variants = [
        "https://example.com/post",
        "http://example.com/post",
        "https://example.com/post/",
        "https://EXAMPLE.com/post?utm_source=twitter",
        "example.com/post#section-2",
    ]
    canonicals = {repair_and_normalise(v).canonical for v in variants}
    assert len(canonicals) == 1, f"expected one canonical form, got {canonicals}"


INVALID_CASES = [
    ("", "empty input"),
    ("   ", "whitespace only"),
    ("not a url", "no valid hostname"),
    ("file:///etc/passwd", "file scheme is refused, not rewritten"),
    ("javascript:alert(1)", "javascript scheme"),
    ("ftp://example.com/x", "ftp scheme"),
    ("https://user:pass@example.com/x", "embedded credentials are out of scope"),
    ("https://localhost/x", "not a public hostname"),
    ("https://example/x", "no TLD"),
]


@pytest.mark.parametrize("raw,why", INVALID_CASES)
def test_invalid_urls_are_rejected(raw, why):
    with pytest.raises(InvalidURL):
        repair_and_normalise(raw)


def test_repairs_are_reported():
    """The user should be able to see what we did to their input."""
    result = repair_and_normalise("EXAMPLE.com/post/?utm_source=x")
    joined = " ".join(result.repairs)
    assert "scheme" in joined
    assert "trailing slash" in joined
    assert "tracking" in joined


# ---------------------------------------------------------------------------
# SSRF guard
#
# These test the GUARD, not the environment. Day 2's peer review recorded the
# mistake of concluding a URL was safe because nothing happened to be
# listening on that address -- on a cloud VM the same request returns IAM
# credentials. So these assert on the refusal, using literal IPs whose class
# is fixed and does not depend on DNS or on what is running locally.
# ---------------------------------------------------------------------------

BLOCKED_ADDRESSES = [
    ("127.0.0.1", "IPv4 loopback"),
    ("::1", "IPv6 loopback"),
    ("169.254.169.254", "AWS/GCP cloud metadata endpoint"),
    ("10.0.0.1", "private class A"),
    ("172.16.0.1", "private class B"),
    ("192.168.1.1", "private class C"),
    ("0.0.0.0", "unspecified"),
]


@pytest.mark.parametrize("host,why", BLOCKED_ADDRESSES)
def test_private_addresses_are_blocked(host, why):
    with pytest.raises(BlockedURL):
        assert_public_address(host)


def test_localhost_name_is_blocked():
    """Blocked on the RESOLVED address, not on the name.

    Name-based blocklists are trivially bypassed: an attacker controls DNS
    for their own domain and can point it at 127.0.0.1. Resolving first is
    what makes the check meaningful.
    """
    with pytest.raises(BlockedURL):
        assert_public_address("localhost")
