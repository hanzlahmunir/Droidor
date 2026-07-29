"""Fetch a URL and return its readable text.

SECURITY: the URL comes from the model, which can be influenced by the user or
by text on a previously-fetched page. That makes this attacker-controlled input
and the tool a Server-Side Request Forgery (SSRF) vector: without guards, the
model could be talked into fetching http://169.254.169.254/ (cloud metadata,
often containing credentials) or http://localhost:5432/ to probe internal
services that are only reachable from this machine.

The defence has four parts, and all four are necessary:
  1. Scheme allowlist        -- blocks file://, gopher://, ftp://
  2. DNS-resolve then check  -- a public hostname can resolve to 127.0.0.1, so
                                checking the hostname STRING is not enough
  3. Re-check every redirect -- a public URL can 302 to an internal one, so we
                                follow redirects manually, validating each hop
  4. Timeout + size cap      -- prevents hanging on a slow server or pulling a
                                multi-GB file into memory
"""

import ipaddress
import socket

import httpx
from selectolax.parser import HTMLParser

_ALLOWED_SCHEMES = {"http", "https"}
_TIMEOUT_SECONDS = 10.0
_MAX_BYTES = 2_000_000  # 2 MB ceiling on the downloaded body
_MAX_REDIRECTS = 5

# Characters-of-text cap. Separate from _MAX_BYTES: that bounds the download,
# this bounds what we hand back to the model. Full page text can be tens of
# thousands of tokens, and (critically) it would then be resent on EVERY
# subsequent turn as part of history. See docs/COST.md.
_MAX_TEXT_CHARS = 6000


class FetchError(RuntimeError):
    """Raised when a URL is unsafe to fetch or cannot be fetched."""


def _assert_safe_url(url: str) -> None:
    """Validate scheme and confirm the host does not resolve to a private IP."""
    try:
        parsed = httpx.URL(url)
    except Exception as exc:
        raise FetchError(f"Malformed URL: {exc}") from None

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise FetchError(
            f"Blocked scheme {parsed.scheme!r}; only http and https are allowed."
        )

    host = parsed.host
    if not host:
        raise FetchError("URL has no host.")

    # Resolve the hostname to every address it maps to. We must check ALL of
    # them: a hostname can return both a public and a private A record, and
    # httpx may connect to any of them.
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host {host!r}: {exc}") from None

    for entry in addr_info:
        raw_ip = entry[4][0]
        ip = ipaddress.ip_address(raw_ip)
        # Covers 127.0.0.0/8 (loopback), 10/172.16/192.168 (private),
        # 169.254.0.0/16 (link-local, i.e. cloud metadata), ::1, fc00::/7,
        # and reserved/multicast ranges.
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FetchError(
                f"Blocked: {host!r} resolves to non-public address {raw_ip}."
            )


def _extract_text(html: str) -> str:
    """Strip markup and return readable text."""
    tree = HTMLParser(html)

    # Remove elements whose text content is noise, so the model's context is
    # not filled with minified JavaScript.
    for tag in ("script", "style", "noscript", "svg", "nav", "footer", "header"):
        for node in tree.css(tag):
            node.decompose()

    body = tree.body
    text = body.text(separator="\n", strip=True) if body else tree.text(strip=True)

    # Collapse runs of blank lines left behind by the removals above.
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_url(url: str) -> str:
    """Fetch a URL and return extracted text, raising FetchError on failure."""
    current_url = url

    # Redirects are followed manually so each hop can be re-validated. With
    # follow_redirects=True, httpx would transparently follow a 302 from a
    # public URL to http://127.0.0.1 and defeat the check entirely.
    for _ in range(_MAX_REDIRECTS):
        _assert_safe_url(current_url)

        try:
            with httpx.Client(
                timeout=_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "Droidor-Day2-CLI-Chat/1.0"},
            ) as client:
                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("Redirect response had no Location header.")
                        # Resolve relative redirects against the current URL.
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    response.raise_for_status()

                    content_type = response.headers.get("content-type", "")
                    if not any(
                        t in content_type for t in ("text/html", "text/plain", "json", "xml")
                    ):
                        raise FetchError(
                            f"Unsupported content type {content_type!r}; "
                            "this tool only reads text pages."
                        )

                    # Enforce the size cap WHILE streaming. Reading the whole
                    # body then checking len() would already have allocated it.
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            raise FetchError(
                                f"Page exceeds {_MAX_BYTES // 1_000_000} MB limit."
                            )
                        chunks.append(chunk)

                    raw = b"".join(chunks).decode(
                        response.encoding or "utf-8", errors="replace"
                    )

        except httpx.HTTPStatusError as exc:
            raise FetchError(
                f"Server returned {exc.response.status_code} for {current_url}"
            ) from None
        except httpx.TimeoutException:
            raise FetchError(
                f"Timed out after {_TIMEOUT_SECONDS:.0f}s fetching {current_url}"
            ) from None
        except httpx.HTTPError as exc:
            raise FetchError(f"Network error fetching {current_url}: {exc}") from None

        text = _extract_text(raw) if "html" in content_type else raw.strip()

        if not text:
            raise FetchError("Page contained no readable text.")

        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "\n\n[... truncated ...]"

        return text

    raise FetchError(f"Too many redirects (more than {_MAX_REDIRECTS}).")
