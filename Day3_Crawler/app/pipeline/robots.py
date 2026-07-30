"""robots.txt compliance.

The rule the task states is "respect robots.txt", and respecting it means
three things, not one:

  1. Do not fetch paths that are Disallowed for our user-agent.
  2. Honour Crawl-delay when it is stricter than our own delay.
  3. Fetch robots.txt itself once per host, not once per URL.

Point 3 matters more than it looks: a naive implementation re-downloads
robots.txt before every article, which triples the request count against a
site we are trying to be polite to.

WHY urllib.robotparser AND NOT A HAND-ROLLED PARSER.
robots.txt has genuinely fiddly semantics -- longest-match wins between
Allow and Disallow, wildcards, $ anchoring, per-agent group selection. The
standard library implements them and is battle-tested. Writing our own would
be a source of silent over-permissiveness, which is the failure mode that
actually gets a crawler banned.

FAIL-CLOSED vs FAIL-OPEN, and why we do BOTH depending on the reason:
  404 / no robots.txt   -> allow. This is the standard's own default: no
                           robots.txt means no restrictions.
  5xx / timeout / error -> REFUSE. We could not read the site's rules, so we
                           do not get to assume they permit us. This is the
                           conservative reading and the one that cannot
                           accidentally crawl something forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Config


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    reason: str | None = None
    crawl_delay: float | None = None
    """Crawl-delay in seconds, if the site specified one for our agent."""


class RobotsCache:
    """Per-host robots.txt, fetched once and reused for the whole run.

    Not persisted between runs: robots.txt can change, and a cache that
    outlived the process could keep us crawling something the site started
    disallowing an hour ago. In-memory for the run is the right lifetime.
    """

    def __init__(self, config: Config, client: httpx.Client) -> None:
        self._config = config
        self._client = client
        # host -> parser, or None when the host has no usable robots.txt
        self._parsers: dict[str, RobotFileParser | None] = {}
        # Hosts whose robots.txt could not be read for a reason that means
        # "refuse" rather than "allow".
        self._unreadable: dict[str, str] = {}

    def _load(self, scheme: str, host: str) -> None:
        """Fetch and parse robots.txt for one host. Called at most once."""
        url = f"{scheme}://{host}/robots.txt"
        try:
            response = self._client.get(url, timeout=self._config.request_timeout_seconds)
        except httpx.HTTPError as exc:
            # Network failure reading the rules -> we do not know them.
            self._parsers[host] = None
            self._unreadable[host] = f"could not fetch robots.txt ({type(exc).__name__})"
            return

        if response.status_code == 404:
            # No robots.txt at all: the standard's default is "everything is
            # allowed". Explicitly NOT an error.
            self._parsers[host] = None
            return

        if response.status_code in (401, 403):
            # The site is actively refusing to show us its rules. Treating
            # that as permission would be perverse.
            self._parsers[host] = None
            self._unreadable[host] = (
                f"robots.txt returned {response.status_code} (access denied)"
            )
            return

        if response.status_code >= 500:
            self._parsers[host] = None
            self._unreadable[host] = f"robots.txt returned {response.status_code}"
            return

        parser = RobotFileParser()
        parser.set_url(url)
        try:
            # parse() takes a list of lines. Decoding errors are tolerated
            # because robots.txt files in the wild are not reliably UTF-8 and
            # a mojibake comment must not break rule parsing.
            parser.parse(response.text.splitlines())
        except Exception as exc:  # noqa: BLE001 - malformed file, not our bug
            self._parsers[host] = None
            self._unreadable[host] = f"robots.txt could not be parsed ({exc})"
            return

        self._parsers[host] = parser

    def check(self, url: str, host: str, scheme: str = "https") -> RobotsVerdict:
        """May we fetch `url`? Fetches robots.txt for the host if needed."""
        if host not in self._parsers:
            self._load(scheme, host)

        if host in self._unreadable:
            return RobotsVerdict(
                allowed=False,
                reason=f"robots.txt unreadable, so crawling is refused: {self._unreadable[host]}",
            )

        parser = self._parsers.get(host)
        if parser is None:
            # No robots.txt -> no restrictions.
            return RobotsVerdict(allowed=True)

        agent = self._config.user_agent

        if not parser.can_fetch(agent, url):
            return RobotsVerdict(
                allowed=False,
                reason="robots.txt disallows this path for our user-agent",
            )

        # crawl_delay() returns the value for the group matching our agent,
        # falling back to the "*" group. None means unspecified.
        delay = None
        try:
            raw_delay = parser.crawl_delay(agent)
            if raw_delay is not None:
                delay = float(raw_delay)
        except (ValueError, TypeError):
            # A malformed Crawl-delay is ignored rather than fatal: the
            # Disallow rules are the part that must be obeyed, and our own
            # default delay still applies.
            delay = None

        return RobotsVerdict(allowed=True, crawl_delay=delay)
