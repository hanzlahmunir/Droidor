"""URL repair and normalisation.

Two jobs that look similar and are not:

  REPAIR   turns what a human typed into something fetchable.
           "example.com/post " -> "https://example.com/post"
           Forgiving on purpose: the user should not have to type a scheme.

  NORMALISE turns a fetchable URL into a canonical key for identity.
           "HTTPS://Example.com/Post/?utm_source=x#intro"
             -> "https://example.com/Post"
           Strict on purpose: two spellings of one article must produce one
           key, or the duplicate check silently misses them.

Normalisation is what makes Day 1's `uq_documents_url` constraint mean
something. Without it the database happily stores the same article five times
under five tracking-parameter variants, and every 409 we rely on never fires.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that identify the CAMPAIGN that sent a visitor, never the
# content. Stripping them collapses the tracking-variant copies of one article
# into a single identity.
#
# Prefix families (utm_*, ga_*) are matched as prefixes; the rest are exact.
_TRACKING_PREFIXES = ("utm_", "ga_", "pk_", "mtm_", "hsa_", "matomo_")
_TRACKING_EXACT = frozenset({
    "fbclid",      # Facebook
    "gclid",       # Google Ads
    "dclid",       # DoubleClick
    "msclkid",     # Microsoft Ads
    "twclid",      # Twitter/X
    "igshid",      # Instagram
    "mc_cid",      # Mailchimp campaign
    "mc_eid",      # Mailchimp recipient
    "_hsenc",      # HubSpot
    "_hsmi",       # HubSpot
    "vero_id",
    "wickedid",
    "yclid",       # Yandex
    "ref",         # generic referrer breadcrumb
    "referrer",
    "source",
    "src",
    "campaign",
    "spm",         # Alibaba-family tracking
    "scid",
})

# Schemes we will fetch. Anything else -- file:, javascript:, data:, ftp: --
# is rejected rather than repaired. A crawler that follows file:// URLs will
# happily read the container's own filesystem when handed a crafted link.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Default ports, removed because ":443" and nothing are the same host.
_DEFAULT_PORTS = {"http": "80", "https": "443"}

# A hostname must have at least one dot and end in letters -- enough to reject
# "not a url" and "localhost typo" without shipping a TLD list that goes stale.
# Deliberately permissive: real validation is whether DNS resolves it.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)"                      # total length limit
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"  # one or more labels + dot
    r"[a-z]{2,63}$"                        # TLD, letters only
)

# Fragments that are really routes, not in-page anchors. A bare "#intro" is a
# scroll target and must be dropped; "#!/2019/03/post" is a hashbang route and
# dropping it would collapse every article on that site to one URL.
_ROUTING_FRAGMENT_RE = re.compile(r"^!?/")


class InvalidURL(ValueError):
    """Raised when a string cannot be repaired into a fetchable http(s) URL."""


class BlockedURL(InvalidURL):
    """Raised when a URL is syntactically fine but must not be fetched.

    Separate from InvalidURL so the caller can tell "you typed this wrong"
    apart from "this resolves somewhere we refuse to go", even though both
    end the crawl for that URL.
    """


def assert_public_address(host: str) -> None:
    """Refuse hosts that resolve to a non-public IP address.

    WHY THIS EXISTS. This crawler fetches URLs supplied by a user through a
    web UI. Without this check, "http://169.254.169.254/latest/meta-data/"
    typed into that box makes the SERVER fetch its own cloud metadata
    endpoint -- which on AWS/GCP serves IAM credentials -- and then renders
    the result on the page. Same for 127.0.0.1 (other containers, admin
    panels bound to loopback) and 10.x/192.168.x (the internal network).
    That is server-side request forgery, and a URL box is the classic way in.

    Day 2's peer review found exactly this hole in the co-intern's fetch_url
    tool: it returned the contents of a file on 127.0.0.1 plus a directory
    listing. My first pass at that review wrongly called it safe because the
    metadata address "errored" -- but only because nothing was listening on
    that laptop. On a cloud VM the same request succeeds. The lesson recorded
    then, applied here: test the guard, not the environment.

    RESOLVE FIRST, THEN CHECK. The check is against the resolved IPs, not the
    hostname string. A blocklist of names is trivially bypassed: an attacker
    controls DNS for their own domain and can point evil.example.com at
    127.0.0.1. Only the resolved address tells the truth.

    Residual limitation, stated honestly: this is a DNS-rebinding race. The
    name could resolve to a public IP here and a private one microseconds
    later when httpx resolves it again. Closing that fully means pinning the
    connection to the IP we validated, which httpx does not expose cleanly.
    For an educational crawler fetching public blogs, the check-then-connect
    window is an accepted, documented risk rather than an unnoticed one.
    """
    try:
        # AF_UNSPEC so both A and AAAA records are considered: a host with a
        # public IPv4 and a loopback IPv6 must still be refused.
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC)
    except socket.gaierror as exc:
        raise InvalidURL(f"Hostname {host!r} does not resolve ({exc.strerror}).") from exc

    if not infos:
        raise InvalidURL(f"Hostname {host!r} does not resolve.")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # is_global is False for loopback, link-local (169.254.x, the cloud
        # metadata range), private (10/8, 172.16/12, 192.168/16), multicast,
        # reserved and unspecified -- one property covering every case, rather
        # than a hand-maintained list of CIDRs that will miss one.
        if not ip.is_global:
            raise BlockedURL(
                f"{host!r} resolves to the non-public address {ip}; refusing to fetch."
            )


@dataclass(frozen=True)
class NormalisedURL:
    """The result of repairing and normalising one input string.

    `repairs` is kept because the report states what had to be fixed, and
    because a user who typed something odd deserves to see what we did with
    it rather than being silently redirected somewhere else.
    """

    canonical: str
    """The normalised form. Use this as the identity key for deduplication."""

    fetch_url: str
    """What to actually request. Currently identical to `canonical`; kept
    distinct because a future signed/paginated URL might need a parameter
    that must not participate in identity."""

    host: str
    """Lowercased hostname, without port. The rate limiter and robots cache
    key on this."""

    repairs: tuple[str, ...]
    """Human-readable list of what was changed, e.g. ("added https:// scheme",
    "removed tracking parameters: utm_source, utm_medium")."""


def _strip_tracking_params(query: str) -> tuple[str, list[str]]:
    """Remove tracking parameters, preserving everything else in order.

    Order is preserved rather than sorted. Sorting would produce a slightly
    tidier key, but some sites genuinely depend on parameter order, and
    fetch_url is derived from this -- correctness beats tidiness.

    keep_blank_values=True matters: "?print=" is not the same page as "?print"
    on some CMSes, and silently dropping the empty value changes the request.
    """
    if not query:
        return "", []

    pairs = parse_qsl(query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    dropped: list[str] = []

    for key, value in pairs:
        lowered = key.lower()
        is_tracking = lowered in _TRACKING_EXACT or lowered.startswith(_TRACKING_PREFIXES)
        if is_tracking:
            dropped.append(key)
        else:
            # NOT dropped: parameters that select content. "?p=123" on
            # WordPress and "?id=" on many CMSes ARE the article -- stripping
            # them would turn every URL on the site into the homepage, which
            # is the classic over-aggressive-normalisation bug.
            kept.append((key, value))

    return urlencode(kept), dropped


def _normalise_path(path: str) -> tuple[str, list[str]]:
    """Collapse duplicate slashes and drop a single trailing slash.

    Case is deliberately PRESERVED. Hostnames are case-insensitive per RFC
    3986; paths are not. Lowercasing "/Blog/My-Post" would 404 on any
    case-sensitive server, and most Unix-backed sites are case-sensitive.
    """
    repairs: list[str] = []

    if "//" in path:
        path = re.sub(r"/{2,}", "/", path)
        repairs.append("collapsed duplicate slashes in path")

    # "/post/" and "/post" are the same document essentially everywhere. The
    # root path "/" is left alone -- it is not a trailing slash, it IS the path.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
        repairs.append("removed trailing slash")

    return path, repairs


def repair_and_normalise(raw: str) -> NormalisedURL:
    """Turn user input into a canonical, fetchable URL.

    Raises InvalidURL only after every repair has been attempted, so the
    INVALID_URL status genuinely means "unfixable", not "slightly untidy".

    PURE AND OFFLINE BY DESIGN: this function performs no DNS and no network
    I/O, so the whole normalisation test suite runs deterministically with no
    network in CI. The SSRF check needs DNS, so it lives in the separate
    `assert_public_address()` and is called by the fetcher immediately before
    connecting -- which is also the latest, and therefore most accurate,
    moment to check.
    """
    repairs: list[str] = []

    if raw is None or not str(raw).strip():
        raise InvalidURL("Empty input.")

    candidate = str(raw).strip()

    # Strip wrapping punctuation from a copy-paste out of prose or markdown:
    # <https://x.com>, "https://x.com", (https://x.com), and combinations
    # like `<https://x.com>.` at the end of a sentence.
    #
    # Looped until stable rather than done in one pass: a single
    # strip-then-rstrip leaves the ">" behind in "<https://x.com>." because
    # the trailing "." blocks it. Found by testing that exact input.
    before = candidate
    while True:
        stripped = candidate.strip("<>\"'`()[]").strip().rstrip(".,;:!?")
        if stripped == candidate:
            break
        candidate = stripped
    if candidate != before:
        repairs.append("removed surrounding punctuation")

    # Internal whitespace from a line-wrapped paste. A URL cannot contain raw
    # whitespace, so removing it is unambiguous rather than a guess.
    if re.search(r"\s", candidate):
        candidate = re.sub(r"\s+", "", candidate)
        repairs.append("removed whitespace")

    if not candidate:
        raise InvalidURL("Nothing left after cleaning the input.")

    # Add a scheme if missing -- the case you asked for specifically.
    #
    # The check is for "://" rather than ":" because "example.com:8080/x" has
    # a colon but no scheme; treating "example.com" as a scheme there would
    # mangle it. Anything with a real scheme that is not http(s) is rejected
    # below rather than rewritten.
    if "://" not in candidate:
        if candidate.startswith("//"):
            # Protocol-relative "//example.com/post"
            candidate = "https:" + candidate
            repairs.append("added https: to protocol-relative URL")
        else:
            candidate = "https://" + candidate
            repairs.append("added https:// scheme")

    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise InvalidURL(f"Could not parse as a URL: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        # Not repairable: file:, javascript:, data:, ftp:. Refusing beats
        # guessing -- a crawler that "helpfully" rewrites file:// into
        # https:// is one that can be steered into reading local files.
        raise InvalidURL(
            f"Unsupported scheme {scheme!r}; only http and https are crawled."
        )

    if scheme == "http":
        # Upgrade to https and let the fetcher fall back if the host genuinely
        # has no TLS. This keeps http:// and https:// spellings of one article
        # from counting as two documents.
        scheme = "https"
        repairs.append("upgraded http to https")

    # netloc may carry credentials and a port: user:pass@host:8080
    netloc = parts.netloc
    if "@" in netloc:
        # Credentials in a URL mean this is authenticated content, which the
        # task puts out of scope. Refusing is also the safe choice: we must
        # never transmit a credential we were handed in a link.
        raise InvalidURL(
            "URL contains embedded credentials; authenticated pages are out of scope."
        )

    host, _, port = netloc.partition(":")
    host = host.lower().strip(".")   # trailing-dot FQDN form: "example.com."

    if not host:
        raise InvalidURL("No hostname found.")

    # IDN -> punycode, so a Unicode domain has one canonical spelling.
    try:
        host_ascii = host.encode("idna").decode("ascii")
        if host_ascii != host:
            repairs.append("converted internationalised domain to punycode")
        host = host_ascii
    except UnicodeError:
        # A host that will not encode as IDNA cannot be resolved either.
        raise InvalidURL(f"Invalid internationalised hostname: {host!r}") from None

    if not _HOSTNAME_RE.match(host):
        raise InvalidURL(
            f"{host!r} is not a valid public hostname "
            "(needs a domain and a letters-only TLD)."
        )

    if port and port != _DEFAULT_PORTS.get(scheme):
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            raise InvalidURL(f"Invalid port {port!r}.")
        netloc_out = f"{host}:{port}"
    else:
        if port:
            repairs.append("removed default port")
        netloc_out = host

    path, path_repairs = _normalise_path(parts.path or "/")
    repairs.extend(path_repairs)

    query, dropped = _strip_tracking_params(parts.query)
    if dropped:
        repairs.append("removed tracking parameters: " + ", ".join(dropped))

    # Fragments are client-side and never sent to the server, so an anchor
    # cannot identify a different document -- except for hashbang routes,
    # where it is the only thing distinguishing two pages.
    fragment = ""
    if parts.fragment:
        if _ROUTING_FRAGMENT_RE.match(parts.fragment):
            fragment = parts.fragment
        else:
            repairs.append("removed #fragment")

    canonical = urlunsplit((scheme, netloc_out, path, query, fragment))

    return NormalisedURL(
        canonical=canonical,
        fetch_url=canonical,
        host=host,
        repairs=tuple(repairs),
    )
