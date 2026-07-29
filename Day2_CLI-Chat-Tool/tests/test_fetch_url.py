"""SSRF guards on the URL fetcher.

The model chooses the URL, so this is attacker-influenced input. These tests
are offline: they assert the request is refused BEFORE any network call, which
is the whole point of the guard.
"""

import pytest

from app.tools.fetch_url import FetchError, _assert_safe_url


@pytest.mark.parametrize(
    "url,reason",
    [
        ("file:///etc/passwd", "local file read"),
        ("ftp://example.com/x", "non-http scheme"),
        ("gopher://example.com/", "non-http scheme"),
        ("not-a-url", "no scheme"),
    ],
)
def test_scheme_allowlist(url, reason):
    with pytest.raises(FetchError, match="[Bb]locked"):
        _assert_safe_url(url)


@pytest.mark.parametrize(
    "url,target",
    [
        ("http://127.0.0.1/", "loopback"),
        ("http://localhost:8080/", "loopback by name"),
        ("http://[::1]/", "IPv6 loopback"),
        ("http://10.0.0.1/", "private range"),
        ("http://192.168.1.1/", "private range"),
        ("http://172.16.0.1/", "private range"),
        # The one that matters most: cloud instance metadata, which serves
        # IAM credentials to anything that can reach it.
        ("http://169.254.169.254/latest/meta-data/", "link-local metadata"),
    ],
)
def test_private_addresses_are_blocked(url, target):
    with pytest.raises(FetchError, match="non-public address"):
        _assert_safe_url(url)


def test_public_url_passes_validation():
    """Guard must not be so strict it blocks legitimate use."""
    _assert_safe_url("https://example.com")


def test_unresolvable_host_is_an_error_not_a_crash():
    with pytest.raises(FetchError, match="Could not resolve"):
        _assert_safe_url("https://nonexistent-abc123xyz.invalid/")
