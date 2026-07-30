"""Rate limiting: hourly, daily and monthly, per-host and globally.

Checked BEFORE any network call, so a refusal costs the target site nothing.

WHY ROLLING WINDOWS, NOT CALENDAR BUCKETS.
A calendar-hour counter ("requests so far this clock hour") resets at :00.
With a limit of 60/hour, a crawler can fire 60 requests at 10:59 and 60 more
at 11:00 -- 120 requests in two minutes, while never technically exceeding
the limit. A rolling window asks "how many in the last 60 minutes", which
cannot be gamed that way. The cost is a COUNT query instead of reading a
counter, which at this scale is free and is why request_log is indexed on
(host, requested_at).

WHY TWO SCOPES.
  per-host   politeness. Protects the site being crawled, and is what keeps
             us off blocklists.
  global     our own budget. Stops a run over 50 hosts from making 3,000
             requests just because no single host saw more than 60.
Neither implies the other, so both are enforced.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Config
from app.storage.models import RequestLog

# Window lengths. A "month" is 30 days rather than a calendar month: the
# limit is about our footprint over time, and 30 days is both simpler and
# stricter than a calendar month that can be 31 days long.
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)
_MONTH = timedelta(days=30)


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a limit check.

    `retry_after_seconds` is computed from the oldest request in the window:
    that request is what will age out first, so it is when the window
    genuinely reopens. Returning a guessed constant instead would either
    waste time or retry too early and be refused again.
    """

    allowed: bool
    reason: str | None = None
    retry_after_seconds: int | None = None

    def message(self) -> str:
        if self.allowed:
            return "allowed"
        wait = ""
        if self.retry_after_seconds is not None:
            mins = max(1, round(self.retry_after_seconds / 60))
            wait = f" Retry in about {mins} min."
        return f"{self.reason}.{wait}"


class RateLimiter:
    """Persistent, DB-backed rate limiter.

    Instantiated per run and handed the same Session the pipeline uses, so a
    request that is recorded and a document that is stored commit together.
    """

    def __init__(self, session: Session, config: Config) -> None:
        self._session = session
        self._config = config
        # Last request time per host, in-process. Used only for the polite
        # inter-request DELAY (a sub-second concern); the LIMITS above are
        # always answered from the database. Keeping the delay in memory
        # avoids a DB round-trip before every single fetch.
        self._last_request_at: dict[str, float] = {}

    # ---------- internals ----------

    def _count_since(self, since: datetime, host: str | None = None) -> int:
        """Number of requests logged since `since`, optionally for one host."""
        stmt = select(func.count()).select_from(RequestLog).where(
            RequestLog.requested_at >= since
        )
        if host is not None:
            stmt = stmt.where(RequestLog.host == host)
        return self._session.execute(stmt).scalar_one()

    def _oldest_in_window(self, since: datetime, host: str | None = None) -> datetime | None:
        """Timestamp of the oldest request still inside the window."""
        stmt = select(func.min(RequestLog.requested_at)).where(
            RequestLog.requested_at >= since
        )
        if host is not None:
            stmt = stmt.where(RequestLog.host == host)
        return self._session.execute(stmt).scalar_one()

    def _check_window(
        self,
        *,
        now: datetime,
        window: timedelta,
        limit: int,
        host: str | None,
        label: str,
    ) -> RateLimitDecision | None:
        """Check one window. Returns a refusal, or None if this window is fine."""
        since = now - window
        used = self._count_since(since, host)
        if used < limit:
            return None

        # The window reopens when the oldest request in it ages out.
        oldest = self._oldest_in_window(since, host)
        retry_after = None
        if oldest is not None:
            # Both sides are timezone-aware (the column is TIMESTAMPTZ and
            # `now` is aware), so this subtraction is safe. Mixing naive and
            # aware datetimes here would raise TypeError -- the reason
            # _utcnow() in models.py is explicit about timezones.
            reopens_at = oldest + window
            retry_after = max(0, int((reopens_at - now).total_seconds()))

        scope = f"host {host}" if host else "global"
        return RateLimitDecision(
            allowed=False,
            reason=(
                f"Rate limit reached for {scope}: "
                f"{used}/{limit} requests in the last {label}"
            ),
            retry_after_seconds=retry_after,
        )

    # ---------- public API ----------

    def check(self, host: str, now: datetime | None = None) -> RateLimitDecision:
        """Would a request to `host` be allowed right now?

        Read-only: this does NOT consume budget. Call `record()` after the
        request actually goes out. Splitting them means a request refused
        later in the pipeline (by robots.txt, say) does not burn budget it
        never used.

        Windows are checked shortest-first so the error names the tightest
        limit that is actually binding, which is the useful one to report.
        """
        now = now or datetime.now(timezone.utc)

        checks = [
            # per-host first: politeness to the site outranks our own budget
            (_HOUR, self._config.max_requests_per_host_hour, host, "hour"),
            (_DAY, self._config.max_requests_per_host_day, host, "day"),
            (_HOUR, self._config.max_requests_global_hour, None, "hour"),
            (_DAY, self._config.max_requests_global_day, None, "day"),
            (_MONTH, self._config.max_requests_global_month, None, "30 days"),
        ]

        for window, limit, scope_host, label in checks:
            refusal = self._check_window(
                now=now, window=window, limit=limit, host=scope_host, label=label
            )
            if refusal is not None:
                return refusal

        return RateLimitDecision(allowed=True)

    def wait_for_host_delay(self, host: str, min_delay_seconds: float | None = None) -> float:
        """Sleep until enough time has passed since the last request to `host`.

        This is the politeness delay, separate from the limits above: even
        well inside every quota, we do not hit one host faster than once per
        `per_host_delay_seconds`.

        `min_delay_seconds` lets robots.txt Crawl-delay override the default
        -- but only upward. A site asking for 0.1s still gets our floor,
        because their robots.txt tells us what they will tolerate, not what
        is polite for an educational crawler to do.

        Returns how long it actually slept, so the caller can log it.
        """
        delay = max(self._config.per_host_delay_seconds, min_delay_seconds or 0.0)
        last = self._last_request_at.get(host)
        if last is None:
            return 0.0

        elapsed = time.monotonic() - last
        remaining = delay - elapsed
        if remaining <= 0:
            return 0.0

        # monotonic(), not time(), so an NTP correction or a DST change
        # cannot make the crawler think it has waited hours (or go negative).
        time.sleep(remaining)
        return remaining

    def record(self, host: str, now: datetime | None = None) -> None:
        """Log that a request to `host` was actually made.

        Called immediately AFTER the request is issued, whatever its outcome.
        A request that returned 403 or timed out still consumed the site's
        resources and still counts -- counting only successes would let a
        crawler retry a failing host without limit.
        """
        self._session.add(
            RequestLog(host=host, requested_at=now or datetime.now(timezone.utc))
        )
        # Flush so the row is visible to subsequent COUNT queries in this same
        # transaction. Without this, a batch of requests inside one
        # transaction would all see a stale count and blow through the limit.
        self._session.flush()
        self._last_request_at[host] = time.monotonic()

    def usage_summary(self, now: datetime | None = None) -> dict[str, dict[str, int]]:
        """Current global usage per window. Shown in the UI and the report."""
        now = now or datetime.now(timezone.utc)
        return {
            "hour": {
                "used": self._count_since(now - _HOUR),
                "limit": self._config.max_requests_global_hour,
            },
            "day": {
                "used": self._count_since(now - _DAY),
                "limit": self._config.max_requests_global_day,
            },
            "month": {
                "used": self._count_since(now - _MONTH),
                "limit": self._config.max_requests_global_month,
            },
        }
