"""The pipeline: one URL in, one CrawlRecord out.

THE CENTRAL INVARIANT of this file, and the thing that makes the data-quality
report trustworthy:

    every DISTINCT URL produces exactly one crawl_record,
    with exactly one status, whatever happens.

That is why `crawl_one` catches broadly at the end and why every early return
goes through `_finish`. If a URL could vanish silently -- swallowed by an
exception, or returned early without a record -- the report's denominator
would shrink and every percentage in it would be quietly wrong. A crash on
one page must produce a recorded failure, not a missing row.

"DISTINCT" is load-bearing, and the word was earned. Re-crawling a URL that
is already recorded returns the EXISTING record instead of inserting a second
one (see stage 2). Inserting would violate uq_crawl_records_canonical_url --
which it did, crashing the run -- and would also double-count that article in
every percentage, so the report's numbers would drift upward each time
someone re-ran a crawl.

STAGE ORDER is chosen so that the cheapest and most polite checks run first.
Anything that lets us refuse without touching the network runs before the
fetch:

    normalise -> URL dupe -> robots -> rate limit -> [FETCH] -> block check
    -> extract -> quality -> content dupe -> near dupe -> date -> push
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.pipeline import blocks, dates, extract
from app.pipeline.api_client import DocumentsAPIClient
from app.pipeline.dedupe import DuplicateDetector
from app.pipeline.fetcher import Fetcher
from app.pipeline.ratelimit import RateLimiter
from app.pipeline.robots import RobotsCache
from app.pipeline.urls import InvalidURL, repair_and_normalise
from app.statuses import CrawlStatus, message_for
from app.storage.models import CrawlRecord


@dataclass
class CrawlOutcome:
    """What happened to one URL, in a form the CLI and UI can both render."""

    input_url: str
    canonical_url: str | None
    status: CrawlStatus
    message: str
    record_id: int | None = None
    document_id: int | None = None
    title: str | None = None
    chars: int = 0


class Pipeline:
    """Runs the full pipeline. One instance per run, reused across URLs.

    Reused deliberately: the robots cache, the HTTP connection pool and the
    duplicate detector's shingle cache all need to persist across URLs to
    avoid re-fetching robots.txt and re-hashing stored articles every time.
    """

    def __init__(
        self,
        session: Session,
        config: Config,
        http_client: httpx.Client,
        api_client: DocumentsAPIClient | None = None,
    ) -> None:
        self._session = session
        self._config = config
        self._robots = RobotsCache(config, http_client)
        self._fetcher = Fetcher(config, http_client)
        self._limiter = RateLimiter(session, config)
        self._dedupe = DuplicateDetector(session, config)
        self._api = api_client or DocumentsAPIClient(config)

    # ------------------------------------------------------------------
    # record helpers
    # ------------------------------------------------------------------

    def _finish(
        self,
        record: CrawlRecord,
        status: CrawlStatus,
        detail: str | None = None,
    ) -> CrawlOutcome:
        """Persist the record with its final status and build the outcome.

        Single exit point for every path through crawl_one, which is what
        enforces the one-URL-one-record invariant.
        """
        record.status = status.value
        record.status_detail = detail
        self._session.add(record)
        # Flush rather than commit: the caller owns the transaction boundary,
        # so a whole run can be rolled back as a unit. Flushing still assigns
        # the id, which the outcome needs.
        self._session.flush()

        return CrawlOutcome(
            input_url=record.input_url,
            canonical_url=record.canonical_url,
            status=status,
            message=message_for(status, detail),
            record_id=record.id,
            document_id=record.api_document_id,
            title=record.title,
            chars=record.text_chars or 0,
        )

    def record_feed_failure(self, feed_url: str, label: str, error: str) -> None:
        """Record that a FEED could not be fetched.

        A feed failure is not an article failure, but it must still be
        visible: it silently removes every article behind it from the run.
        Without this, a run that reached four of five feeds is
        indistinguishable from one that reached all five -- the only clue
        being a smaller total, with nothing saying why.

        Idempotent by canonical URL, so re-running a seed does not accumulate
        duplicate failure rows (and does not trip the unique constraint).
        """
        try:
            normalised = repair_and_normalise(feed_url)
            canonical, host = normalised.canonical, normalised.host
        except InvalidURL:
            canonical, host = feed_url[:2000], ""

        existing = self._session.execute(
            select(CrawlRecord).where(CrawlRecord.canonical_url == canonical)
        ).scalar_one_or_none()
        if existing is not None:
            existing.status = CrawlStatus.FETCH_FAILED.value
            existing.status_detail = f"feed '{label}' could not be fetched: {error}"
            self._session.flush()
            return

        self._session.add(
            CrawlRecord(
                canonical_url=canonical,
                input_url=feed_url[:2000],
                host=host,
                status=CrawlStatus.FETCH_FAILED.value,
                status_detail=f"feed '{label}' could not be fetched: {error}",
            )
        )
        self._session.flush()

    # ------------------------------------------------------------------
    # the pipeline
    # ------------------------------------------------------------------

    def crawl_one(
        self,
        input_url: str,
        *,
        feed_date: str | None = None,
        source_label: str | None = None,
        use_cache: bool = True,
    ) -> CrawlOutcome:
        """Process one URL end to end. Never raises."""
        record = CrawlRecord(
            input_url=(input_url or "")[:2000],
            canonical_url="",
            host="",
            status=CrawlStatus.FETCH_FAILED.value,
        )

        try:
            return self._run_stages(
                record,
                input_url,
                feed_date=feed_date,
                source_label=source_label,
                use_cache=use_cache,
            )
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            # An unexpected exception must still produce a record. Letting it
            # escape would abort the run AND leave this URL uncounted, so the
            # report would be computed over a smaller denominator without
            # anyone noticing. The exception type and message are recorded so
            # the bug is still visible.
            self._session.rollback()
            record.status = CrawlStatus.FETCH_FAILED.value
            record.status_detail = f"unexpected error: {type(exc).__name__}: {exc}"
            self._session.add(record)
            self._session.flush()
            return CrawlOutcome(
                input_url=input_url,
                canonical_url=record.canonical_url or None,
                status=CrawlStatus.FETCH_FAILED,
                message=f"Unexpected error: {type(exc).__name__}: {exc}",
                record_id=record.id,
            )

    def _run_stages(
        self,
        record: CrawlRecord,
        input_url: str,
        *,
        feed_date: str | None,
        source_label: str | None,
        use_cache: bool,
    ) -> CrawlOutcome:
        # ---- 1. normalise ----
        try:
            normalised = repair_and_normalise(input_url)
        except InvalidURL as exc:
            record.canonical_url = f"invalid:{input_url}"[:2000]
            return self._finish(record, CrawlStatus.INVALID_URL, str(exc))

        record.canonical_url = normalised.canonical
        record.host = normalised.host
        record.repairs = "; ".join(normalised.repairs) or None

        # ---- 2. URL duplicate (free, before any network) ----
        verdict = self._dedupe.check_url(normalised.canonical)
        if verdict.is_duplicate:
            # Return WITHOUT inserting a row.
            #
            # This is the one place the "every URL gets a record" rule is
            # deliberately not applied, and it took a crash to see why. The
            # first version inserted a duplicate row here and immediately
            # violated uq_crawl_records_canonical_url -- so re-crawling any
            # known URL blew up. Verified with:
            #   crawl "http://blog.cloudflare.com/bgp-origin-attribute/?utm_source=twitter"
            # which normalises onto an already-stored article.
            #
            # Inserting was wrong on the merits too, not just mechanically.
            # crawl_records is keyed by canonical_url precisely because it
            # holds ONE row per distinct article. A second row for the same
            # URL would double-count that article in every percentage the
            # report computes -- the denominator would grow each time anyone
            # re-ran a crawl, and the numbers would drift with usage.
            #
            # The existing record already carries this URL's outcome, so it is
            # returned instead. The report stays a count of distinct URLs.
            existing_id = verdict.duplicate_of_id
            return CrawlOutcome(
                input_url=input_url,
                canonical_url=normalised.canonical,
                status=CrawlStatus.DUPLICATE_URL,
                message=message_for(CrawlStatus.DUPLICATE_URL, verdict.detail),
                record_id=existing_id,
            )

        # ---- 3. robots.txt ----
        # Before the rate-limit check: a disallowed URL must not consume
        # budget, since we are never going to request it.
        robots_verdict = self._robots.check(normalised.canonical, normalised.host)
        if not robots_verdict.allowed:
            return self._finish(
                record, CrawlStatus.ROBOTS_DISALLOWED, robots_verdict.reason
            )

        # ---- 4. rate limit ----
        decision = self._limiter.check(normalised.host)
        if not decision.allowed:
            return self._finish(record, CrawlStatus.RATE_LIMITED, decision.message())

        # ---- 5. fetch ----
        # Politeness delay first, honouring robots.txt Crawl-delay when it is
        # stricter than our own floor.
        self._limiter.wait_for_host_delay(
            normalised.host, robots_verdict.crawl_delay
        )
        result = self._fetcher.fetch(normalised.canonical, use_cache=use_cache)
        # Recorded whether or not the fetch succeeded: a timeout still cost
        # the site a connection and must count against our budget.
        self._limiter.record(normalised.host)

        record.fetched_at = datetime.now(timezone.utc)
        record.http_status = result.http_status
        record.raw_html_path = result.raw_path

        if not result.ok and not result.html:
            # Nothing at all came back -- no body for the block classifier to
            # inspect, so this is a plain fetch failure.
            return self._finish(record, CrawlStatus.FETCH_FAILED, result.error)

        html = result.html or ""

        # ---- 6. extract (before block classification) ----
        # Deliberately in this order: the block checks need to know how much
        # text a page yielded. "Contains a password field" means nothing on a
        # 9,000-character article and everything on a 200-character one.
        extraction = extract.extract(html, result.final_url or normalised.canonical, self._config)

        record.text_chars = extraction.chars
        record.text_words = extraction.words
        record.headings = extraction.headings
        record.code_blocks = extraction.code_blocks
        record.list_items = extraction.list_items
        record.link_density = extraction.link_density
        record.secondary_text_chars = extraction.secondary_chars
        record.extractor_agreement = extraction.agreement
        record.title = (extraction.title or "")[:1000] or None

        # ---- 7. blocked? ----
        block = blocks.classify(
            html,
            http_status=result.http_status,
            extracted_chars=extraction.chars,
        )
        if block.blocked and block.status is not None:
            return self._finish(record, block.status, block.detail)

        # A non-2xx that was not identified as a wall is just a failed fetch.
        if not result.ok:
            return self._finish(record, CrawlStatus.FETCH_FAILED, result.error)

        # ---- 8. quality gate ----
        if not extraction.ok:
            # "no_text_extracted" means the extractors found nothing at all,
            # which is a different failure from "found text, but it is bad" --
            # and the task asks for both, so they stay separate statuses.
            status = (
                CrawlStatus.EXTRACTION_FAILED
                if "no_text_extracted" in extraction.failed_rules
                or "empty_html" in extraction.failed_rules
                else CrawlStatus.JUNK
            )
            record.text = extraction.text or None
            record.content_hash = extraction.content_hash
            detail = extraction.detail
            if extraction.failed_rules:
                detail = f"[{', '.join(extraction.failed_rules)}] {detail or ''}".strip()
            return self._finish(record, status, detail)

        record.text = extraction.text
        record.content_hash = extraction.content_hash

        # ---- 9. content duplicate (exact) ----
        content_verdict = self._dedupe.check_content(extraction.content_hash or "")
        if content_verdict.is_duplicate:
            record.duplicate_of_id = content_verdict.duplicate_of_id
            record.duplicate_similarity = content_verdict.similarity
            return self._finish(
                record, CrawlStatus.DUPLICATE_CONTENT, content_verdict.detail
            )

        # ---- 10. near duplicate ----
        near_verdict = self._dedupe.check_near(extraction.text)
        # The similarity score is stored even when it is BELOW the threshold,
        # so the report can show how close the nearest non-duplicate was.
        record.duplicate_similarity = near_verdict.similarity
        if near_verdict.is_duplicate:
            record.duplicate_of_id = near_verdict.duplicate_of_id
            return self._finish(
                record, CrawlStatus.DUPLICATE_NEAR, near_verdict.detail
            )

        # ---- 11. publish date ----
        date_result = dates.extract_date(html, self._config, feed_date=feed_date)
        record.published_at = date_result.value
        record.published_at_source = date_result.source
        record.published_at_raw = (date_result.raw or "")[:200] or None

        # ---- 12. push to the Day 1 API ----
        push = self._api.create_document(
            title=extraction.title or record.canonical_url,
            url=normalised.canonical,
            text=extraction.text,
            source=source_label or normalised.host,
            published_at=date_result.value,
        )

        if push.duplicate:
            # The API's unique index rejected it even though our own URL check
            # passed. That means the two disagree -- worth recording as a
            # duplicate rather than a success, and worth seeing in the report.
            return self._finish(
                record,
                CrawlStatus.DUPLICATE_URL,
                "the documents API already has this url (409)",
            )

        if not push.ok:
            return self._finish(record, CrawlStatus.API_REJECTED, push.error)

        record.api_document_id = push.document_id

        detail = None
        if date_result.value is None:
            # Stored, but flagged: a document with no publish date is a
            # success with a caveat, and the report counts it.
            detail = f"stored without a publish date ({date_result.error})"

        return self._finish(record, CrawlStatus.STORED, detail)
