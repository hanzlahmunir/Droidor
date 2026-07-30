"""Command-line interface.

    python -m app.cli crawl <url> [<url> ...]   crawl specific URLs
    python -m app.cli feed <feed-url> [--limit N]
    python -m app.cli seed [--per-feed N]       crawl the five default feeds
    python -m app.cli discover "<topic>" [--crawl]
    python -m app.cli report                    regenerate the report
    python -m app.cli status                    counts + rate-limit usage

Subcommands rather than flags on one command: these do genuinely different
things, and `crawl --report --discover` would be a command whose behaviour
depends on flag combinations nobody can remember.
"""

from __future__ import annotations

import argparse
import sys

from app.config import Config
from app.discover import SearchUnavailable
from app.discover import discover as discover_topic
from app.pipeline.api_client import DocumentsAPIClient
from app.pipeline.crawler import CrawlOutcome, Pipeline
from app.pipeline.fetcher import build_client
from app.pipeline.feeds import fetch_feed
from app.pipeline.ratelimit import RateLimiter
from app.report import write as write_report
from app.seeds import SEED_FEEDS
from app.statuses import CrawlStatus
from app.storage.database import create_schema, session_scope

# Terminal markers for each outcome. Plain ASCII: the Windows console's
# default code page raises UnicodeEncodeError on many symbols, a bug already
# hit and fixed in Day 2.
_MARKERS = {
    CrawlStatus.STORED: "[ok]",
    CrawlStatus.DUPLICATE_URL: "[dup]",
    CrawlStatus.DUPLICATE_CONTENT: "[dup]",
    CrawlStatus.DUPLICATE_NEAR: "[dup]",
    CrawlStatus.ROBOTS_DISALLOWED: "[robots]",
    CrawlStatus.RATE_LIMITED: "[limit]",
    CrawlStatus.LOGIN_REQUIRED: "[login]",
    CrawlStatus.PAYWALL_PARTIAL: "[paywall]",
    CrawlStatus.BOT_WALL: "[botwall]",
}
_DEFAULT_MARKER = "[fail]"


def _print_outcome(outcome: CrawlOutcome) -> None:
    marker = _MARKERS.get(outcome.status, _DEFAULT_MARKER)
    url = outcome.canonical_url or outcome.input_url
    print(f"  {marker:9} {url}")
    if outcome.status is CrawlStatus.STORED:
        title = (outcome.title or "(untitled)")[:70]
        print(f"            {title}  [{outcome.chars} chars, doc #{outcome.document_id}]")
    else:
        print(f"            {outcome.message}")


def _summarise(outcomes: list[CrawlOutcome]) -> None:
    if not outcomes:
        print("\nNothing processed.")
        return
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
    print(f"\n  {len(outcomes)} URLs processed:")
    for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {count:3}  {status}")


def _check_api(config: Config) -> bool:
    """Fail fast with a clear message if the Day 1 API is unreachable.

    Checked up front rather than on the first push: crawling twenty pages
    politely takes a minute, and discovering at the end that nothing could be
    stored wastes that time and the sites' bandwidth.
    """
    if DocumentsAPIClient(config).health():
        return True
    print(
        f"ERROR: the documents API at {config.api_base_url} is not responding.\n"
        "       Start it with `docker compose up` from Day3_Crawler/.",
        file=sys.stderr,
    )
    return False


def cmd_crawl(args: argparse.Namespace, config: Config) -> int:
    if not _check_api(config):
        return 1
    create_schema()
    outcomes: list[CrawlOutcome] = []
    with session_scope() as session, build_client(config) as http:
        pipeline = Pipeline(session, config, http)
        print(f"Crawling {len(args.urls)} URL(s)...\n")
        for url in args.urls:
            outcome = pipeline.crawl_one(url, use_cache=not args.no_cache)
            outcomes.append(outcome)
            _print_outcome(outcome)
    _summarise(outcomes)
    return 0


def _crawl_feed(pipeline: Pipeline, label: str, feed_url: str, config: Config,
                http, limit: int, no_cache: bool) -> list[CrawlOutcome]:
    print(f"\n{label}  <{feed_url}>")
    feed = fetch_feed(feed_url, config, http, limit=limit)
    if not feed.ok:
        # Recorded, not just printed. A feed that fails takes every article
        # behind it with it, and if that vanished silently the report would
        # be computed over a smaller denominator with no indication why --
        # a run that reached 4 of 5 feeds would look identical to one that
        # reached all 5. Seen for real: one run processed 25 URLs and the
        # next 20, because Mozilla's feed timed out.
        #
        # Recorded against the FEED url, so it appears in the report as one
        # fetch_failed row naming the feed rather than as missing articles.
        print(f"  [fail]    {feed.error}")
        pipeline.record_feed_failure(feed_url, label, feed.error or "feed fetch failed")
        return []

    print(f"  {len(feed.entries)} entries")
    outcomes = []
    for entry in feed.entries:
        outcome = pipeline.crawl_one(
            entry.url,
            # The feed's own date, top of the date ladder.
            feed_date=entry.published_raw,
            # The feed's label, so `GET /documents?source=...` groups by blog
            # rather than by hostname.
            source_label=label,
            use_cache=not no_cache,
        )
        outcomes.append(outcome)
        _print_outcome(outcome)
    return outcomes


def cmd_feed(args: argparse.Namespace, config: Config) -> int:
    if not _check_api(config):
        return 1
    create_schema()
    outcomes: list[CrawlOutcome] = []
    with session_scope() as session, build_client(config) as http:
        pipeline = Pipeline(session, config, http)
        outcomes = _crawl_feed(
            pipeline, args.label or args.feed_url, args.feed_url,
            config, http, args.limit, args.no_cache,
        )
    _summarise(outcomes)
    return 0


def cmd_seed(args: argparse.Namespace, config: Config) -> int:
    """Crawl the five default feeds -- the demo run behind `docker compose up`."""
    if not _check_api(config):
        return 1
    create_schema()
    outcomes: list[CrawlOutcome] = []
    print(f"Seeding from {len(SEED_FEEDS)} feeds, up to {args.per_feed} articles each.")
    with session_scope() as session, build_client(config) as http:
        pipeline = Pipeline(session, config, http)
        for label, feed_url in SEED_FEEDS:
            outcomes.extend(
                _crawl_feed(pipeline, label, feed_url, config, http,
                            args.per_feed, args.no_cache)
            )
    _summarise(outcomes)

    with session_scope() as session:
        md_path, json_path = write_report(session, config)
    print(f"\nReport written to {md_path} and {json_path}")
    return 0


def cmd_discover(args: argparse.Namespace, config: Config) -> int:
    print(f"Searching for: {args.topic}\n")
    if not config.groq_api_key:
        print("  (no GROQ_API_KEY -- returning unranked search results)\n")

    try:
        candidates = discover_topic(args.topic, config)
    except SearchUnavailable as exc:
        # Distinct from "no results": search never ran. Reported separately so
        # a network problem is not mistaken for an empty topic.
        print(
            f"Search is unavailable, so no candidates could be found.\n  {exc}\n"
            "  This does not affect crawling: `crawl <url>` and `feed <url>` "
            "work without search.",
            file=sys.stderr,
        )
        return 1

    if not candidates:
        print("Search ran, but returned no results for that topic.")
        return 1

    for index, candidate in enumerate(candidates, start=1):
        score = f"{candidate.score:.2f}" if candidate.score is not None else " -- "
        print(f"  {index:2}. [{score}] {candidate.title[:70]}")
        print(f"          {candidate.url}")
        if candidate.reason:
            print(f"          {candidate.reason}")

    if not args.crawl:
        print("\nRe-run with --crawl to fetch these.")
        return 0

    if not _check_api(config):
        return 1
    create_schema()
    print(f"\nCrawling {len(candidates)} candidates...\n")
    outcomes: list[CrawlOutcome] = []
    with session_scope() as session, build_client(config) as http:
        pipeline = Pipeline(session, config, http)
        for candidate in candidates:
            outcome = pipeline.crawl_one(candidate.url, use_cache=not args.no_cache)
            outcomes.append(outcome)
            _print_outcome(outcome)
    _summarise(outcomes)
    return 0


def cmd_report(args: argparse.Namespace, config: Config) -> int:
    create_schema()
    with session_scope() as session:
        md_path, json_path = write_report(session, config)
    print(f"Report written to:\n  {md_path}\n  {json_path}")
    return 0


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    create_schema()
    from sqlalchemy import func, select

    from app.storage.models import CrawlRecord

    with session_scope() as session:
        rows = session.execute(
            select(CrawlRecord.status, func.count())
            .group_by(CrawlRecord.status)
            .order_by(func.count().desc())
        ).all()
        total = sum(count for _, count in rows)

        print(f"crawl_records: {total} rows")
        for status, count in rows:
            print(f"  {count:4}  {status}")

        print("\nRate-limit usage (global):")
        for window, data in RateLimiter(session, config).usage_summary().items():
            print(f"  {window:6}  {data['used']:5} / {data['limit']}")

        print(f"\nDocuments API: {config.api_base_url}")
        print(f"  reachable: {DocumentsAPIClient(config).health()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler", description="Blog crawler with a data-quality report."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_cache_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--no-cache",
            action="store_true",
            help="Re-fetch even if raw HTML is cached (default: use the cache).",
        )

    p_crawl = sub.add_parser("crawl", help="Crawl one or more URLs.")
    p_crawl.add_argument("urls", nargs="+")
    add_cache_flag(p_crawl)
    p_crawl.set_defaults(func=cmd_crawl)

    p_feed = sub.add_parser("feed", help="Crawl articles from an RSS/Atom feed.")
    p_feed.add_argument("feed_url")
    p_feed.add_argument("--limit", type=int, default=5)
    p_feed.add_argument("--label", default=None, help="`source` for stored documents.")
    add_cache_flag(p_feed)
    p_feed.set_defaults(func=cmd_feed)

    p_seed = sub.add_parser("seed", help="Crawl the five default feeds, then report.")
    p_seed.add_argument("--per-feed", type=int, default=5)
    add_cache_flag(p_seed)
    p_seed.set_defaults(func=cmd_seed)

    p_discover = sub.add_parser("discover", help="Find articles on a topic.")
    p_discover.add_argument("topic")
    p_discover.add_argument("--crawl", action="store_true")
    add_cache_flag(p_discover)
    p_discover.set_defaults(func=cmd_discover)

    sub.add_parser("report", help="Regenerate the report.").set_defaults(func=cmd_report)
    sub.add_parser("status", help="Show counts and rate-limit usage.").set_defaults(
        func=cmd_status
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, Config())


if __name__ == "__main__":
    raise SystemExit(main())
