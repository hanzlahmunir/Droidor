"""Central configuration, read from the environment.

Every threshold the pipeline uses lives here rather than as a magic number
buried in the module that happens to need it. Two reasons:

  1. The data-quality report has to state the rules it measured against
     ("junk = under 300 chars OR link density over 0.5"). Those numbers must
     come from one place, or the report and the code drift apart and the
     report becomes a lie.
  2. Tuning a threshold is then a config change, not a code change, so the
     same cached HTML can be re-scored without touching the pipeline.

Nothing here is a secret except the two optional API keys, and both degrade
gracefully when absent -- the core crawl requires no credentials at all.
"""

import os

from dotenv import load_dotenv

# Load .env into os.environ if present. Real deployments set env vars
# directly, so a missing .env file is not an error.
load_dotenv()


def _int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to a default."""
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


class Config:
    """Runtime settings. Instantiated once at entry and passed down."""

    def __init__(self) -> None:
        # ---------- Where crawled documents go ----------
        # The Day 1 API, addressed over HTTP by its compose hostname. We POST
        # to the API rather than writing to its table directly, deliberately:
        # going around it would leave the 409-on-duplicate path, the 422
        # validation and the whole published_at contract unexercised.
        self.api_base_url: str = os.environ.get(
            "API_BASE_URL", "http://api:8000"
        ).rstrip("/")

        # ---------- The crawler's OWN database ----------
        # Separate from the documents table. This stores rate-limit counters
        # and the per-URL crawl record that the report is generated from.
        self.database_url: str = os.environ["DATABASE_URL"]

        # ---------- Identity ----------
        # A real, contactable User-Agent is the minimum courtesy for a crawler:
        # it lets an operator see who we are and tell us to stop. Anonymous or
        # browser-spoofing agents are what get IP ranges blocked.
        self.user_agent: str = os.environ.get(
            "USER_AGENT",
            "DroidorBlogHarvester/1.0 (+https://github.com/hanzlahmunir; "
            "educational crawler; contact via GitHub issues)",
        )

        # ---------- Politeness ----------
        # Minimum seconds between two requests to the SAME host. robots.txt
        # Crawl-delay overrides this whenever it is stricter (never laxer --
        # a site asking for less delay than our floor still gets our floor).
        self.per_host_delay_seconds: float = _float("PER_HOST_DELAY_SECONDS", 2.0)

        # Bounded so one unresponsive host cannot stall the run.
        self.request_timeout_seconds: float = _float("REQUEST_TIMEOUT_SECONDS", 20.0)

        # Redirects are followed, but capped: a redirect loop across hosts is
        # a cheap way to get a crawler stuck or walked into somewhere it
        # should not be.
        self.max_redirects: int = _int("MAX_REDIRECTS", 5)

        # Refuse absurdly large bodies. An article is text; a 50 MB response
        # is a video, a dump, or a trap.
        self.max_content_bytes: int = _int("MAX_CONTENT_BYTES", 5_000_000)

        # ---------- Rate limits (our own budget) ----------
        # Enforced BEFORE any network call, persisted in Postgres so a restart
        # cannot reset them. Two scopes: per-host (politeness to one site) and
        # global (our total footprint).
        self.max_requests_per_host_hour: int = _int("MAX_REQ_PER_HOST_HOUR", 60)
        self.max_requests_per_host_day: int = _int("MAX_REQ_PER_HOST_DAY", 300)
        self.max_requests_global_hour: int = _int("MAX_REQ_GLOBAL_HOUR", 300)
        self.max_requests_global_day: int = _int("MAX_REQ_GLOBAL_DAY", 2000)
        self.max_requests_global_month: int = _int("MAX_REQ_GLOBAL_MONTH", 20000)

        # ---------- Quality gates ----------
        # An article shorter than this is almost never a real article: it is a
        # stub, a redirect notice, a cookie wall, or a failed extraction. The
        # task predicts exactly this ("your 5 shortest -- they're usually
        # garbage"), so the floor is a reported threshold, not a hidden one.
        self.min_article_chars: int = _int("MIN_ARTICLE_CHARS", 300)

        # Link density = characters inside <a> / total characters. Navigation,
        # tag clouds and "related posts" lists are mostly links; prose is not.
        # Above this ratio we call it navigation rather than an article.
        self.max_link_density: float = _float("MAX_LINK_DENSITY", 0.35)

        # How far the two independent extractors may disagree on length before
        # we distrust the result. 0.5 = the shorter is under half the longer.
        # Sharp disagreement means one of them latched onto the wrong subtree.
        self.extractor_agreement_ratio: float = _float("EXTRACTOR_AGREEMENT_RATIO", 0.5)

        # ---------- Duplicate detection ----------
        # Jaccard similarity over word shingles, above which two articles are
        # "near-duplicates". 0.85 is strict enough that a shared boilerplate
        # footer does not merge two genuinely different posts, loose enough to
        # catch a syndicated repost with a changed intro.
        self.near_duplicate_threshold: float = _float("NEAR_DUPLICATE_THRESHOLD", 0.85)

        # Words per shingle. 5 is the usual choice: long enough that common
        # phrases ("on the other hand") do not collide, short enough to
        # survive light editing.
        self.shingle_size: int = _int("SHINGLE_SIZE", 5)

        # ---------- Publish-date sanity ----------
        # A date outside this window is treated as unparseable rather than
        # stored. Dates before this are usually a Unix-epoch default (1970) or
        # a mis-parsed page number; dates in the future are usually a
        # scheduled-post placeholder or a comment timestamp.
        self.min_plausible_year: int = _int("MIN_PLAUSIBLE_YEAR", 1995)
        # Tolerance for clock skew and genuinely-just-published articles.
        self.future_date_tolerance_days: int = _int("FUTURE_DATE_TOLERANCE_DAYS", 2)

        # ---------- Paths ----------
        # Raw HTML is cached here so the extractor can be re-tuned and the
        # whole corpus re-scored WITHOUT re-crawling. That matters twice: it
        # is polite (we fetch each page once), and it makes the data-quality
        # numbers reproducible from stored input rather than a fresh crawl
        # that would return slightly different pages.
        self.raw_html_dir: str = os.environ.get("RAW_HTML_DIR", "data/raw")
        self.report_dir: str = os.environ.get("REPORT_DIR", "data/reports")

        # ---------- Optional: topic discovery ----------
        # Both absent -> `discover` still works, returning search results in
        # provider order with no LLM ranking. The crawl pipeline itself never
        # needs either key.
        self.groq_api_key: str | None = os.environ.get("GROQ_API_KEY") or None
        self.tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY") or None
        # Same model Day 2 measured as reliable for tool/JSON output.
        self.discovery_model: str = os.environ.get(
            "DISCOVERY_MODEL", "openai/gpt-oss-120b"
        )
