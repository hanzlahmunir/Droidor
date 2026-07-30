"""Streamlit UI: browse stored articles, crawl new ones, discover by topic.

WHY A UI AT ALL. The brief's acceptance test is "you can open any 3 stored
articles and show they're clean". Doing that with curl produces a wall of
escaped JSON that nobody can judge cleanliness from. A page that renders the
stored text is the difference between claiming the corpus is clean and
showing it.

The Browse tab reads through the Day 1 API, not the crawler's database. That
is deliberate: it shows what a real consumer of the API sees, so the
demonstration is of the actual system rather than of the crawler's private
copy.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from app.config import Config
from app.discover import SearchUnavailable
from app.discover import discover as discover_topic
from app.pipeline.api_client import DocumentsAPIClient
from app.pipeline.crawler import Pipeline
from app.pipeline.fetcher import build_client
from app.pipeline.ratelimit import RateLimiter
from app.report import build as build_report
from app.report import write as write_report
from app.statuses import CrawlStatus
from app.storage.database import create_schema, session_scope
from app.storage.models import CrawlRecord

st.set_page_config(page_title="Blog Harvester", page_icon="📰", layout="wide")


@st.cache_resource
def get_config() -> Config:
    """One Config for the session.

    cache_resource, not cache_data: Streamlit re-runs this whole script on
    every interaction, and without caching we would rebuild the config and
    re-read the environment on every click.
    """
    create_schema()
    return Config()


config = get_config()
api = DocumentsAPIClient(config)


def _crawl_urls(urls: list[str], source_label: str | None = None) -> list:
    """Run the pipeline over some URLs, showing live progress."""
    outcomes = []
    progress = st.progress(0.0)
    status_line = st.empty()

    with session_scope() as session, build_client(config) as http:
        pipeline = Pipeline(session, config, http)
        for index, url in enumerate(urls):
            status_line.write(f"Fetching {url}")
            outcomes.append(
                pipeline.crawl_one(url, source_label=source_label)
            )
            progress.progress((index + 1) / len(urls))

    progress.empty()
    status_line.empty()
    return outcomes


def _show_outcomes(outcomes: list) -> None:
    for outcome in outcomes:
        if outcome.status is CrawlStatus.STORED:
            st.success(
                f"**{outcome.title or 'Untitled'}** — {outcome.chars} chars "
                f"(document #{outcome.document_id})\n\n{outcome.canonical_url}"
            )
        elif outcome.status in (
            CrawlStatus.DUPLICATE_URL,
            CrawlStatus.DUPLICATE_CONTENT,
            CrawlStatus.DUPLICATE_NEAR,
        ):
            st.info(f"**Duplicate** — {outcome.message}\n\n{outcome.canonical_url}")
        elif outcome.status in (
            CrawlStatus.LOGIN_REQUIRED,
            CrawlStatus.PAYWALL_PARTIAL,
            CrawlStatus.BOT_WALL,
        ):
            # These get their own colour: they are not crawler failures, they
            # are the site refusing us, and the user should be able to tell
            # the difference at a glance.
            st.warning(f"**Blocked** — {outcome.message}\n\n{outcome.canonical_url}")
        else:
            st.error(f"**{outcome.status.value}** — {outcome.message}\n\n{outcome.input_url}")


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Status")

    if api.health():
        st.success("Documents API: up")
    else:
        st.error(f"Documents API unreachable\n\n{config.api_base_url}")

    with session_scope() as session:
        total = session.execute(select(func.count()).select_from(CrawlRecord)).scalar_one()
        stored = session.execute(
            select(func.count())
            .select_from(CrawlRecord)
            .where(CrawlRecord.status == CrawlStatus.STORED.value)
        ).scalar_one()
        usage = RateLimiter(session, config).usage_summary()

    st.metric("URLs processed", total)
    st.metric("Articles stored", stored)

    st.subheader("Rate limits")
    for window, data in usage.items():
        # A progress bar rather than a number: the useful question is "how
        # close am I to the ceiling", which a ratio answers at a glance.
        ratio = min(1.0, data["used"] / data["limit"]) if data["limit"] else 0.0
        st.caption(f"{window}: {data['used']} / {data['limit']}")
        st.progress(ratio)

    st.caption(f"Politeness delay: {config.per_host_delay_seconds}s per host")


tab_browse, tab_crawl, tab_discover, tab_report = st.tabs(
    ["Browse", "Crawl a URL", "Discover by topic", "Quality report"]
)

# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------

with tab_browse:
    st.header("Stored articles")
    st.caption(
        "Read back through the Day 1 API — this is what any consumer of the "
        "API sees, not the crawler's private copy."
    )

    documents = api.list_documents(limit=100)

    if not documents:
        st.info("Nothing stored yet. Use the Crawl tab, or run `seed` from the CLI.")
    else:
        table = pd.DataFrame(
            [
                {
                    "id": doc["id"],
                    "title": doc["title"][:80],
                    "source": doc["source"],
                    "published": (doc.get("published_at") or "")[:10] or "—",
                    "stored": doc["created_at"][:10],
                    "chars": len(doc["text"]),
                }
                for doc in documents
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)

        st.subheader("Open an article")
        st.caption(
            "This is the acceptance test: open any three and check the text "
            "has no nav, footer, ads or share buttons in it."
        )
        chosen = st.selectbox(
            "Article",
            options=[doc["id"] for doc in documents],
            format_func=lambda doc_id: next(
                f"#{d['id']} — {d['title'][:70]}" for d in documents if d["id"] == doc_id
            ),
        )
        document = next(d for d in documents if d["id"] == chosen)

        left, right = st.columns([2, 1])
        with left:
            st.markdown(f"### {document['title']}")
            st.caption(document["url"])
        with right:
            st.metric("Characters", len(document["text"]))
            st.caption(f"Published: {(document.get('published_at') or '—')[:10]}")
            st.caption(f"Stored: {document['created_at'][:10]}")

        st.text_area("Cleaned text", document["text"], height=420)

# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

with tab_crawl:
    st.header("Crawl a URL")
    st.caption(
        "The scheme is optional and a trailing slash is fine — the URL is "
        "repaired and normalised before anything is fetched."
    )

    with st.form("crawl_form"):
        raw_urls = st.text_area(
            "URL(s), one per line",
            placeholder="example.com/blog/my-post\nhttps://another.com/article/",
            height=120,
        )
        submitted = st.form_submit_button("Crawl", type="primary")

    if submitted:
        urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
        if not urls:
            st.warning("Enter at least one URL.")
        else:
            _show_outcomes(_crawl_urls(urls))

    st.divider()
    st.subheader("Or crawl an RSS feed")
    with st.form("feed_form"):
        feed_url = st.text_input("Feed URL", placeholder="https://example.com/feed.xml")
        per_feed = st.number_input("Max articles", 1, 25, 5)
        feed_submitted = st.form_submit_button("Crawl feed")

    if feed_submitted and feed_url.strip():
        from app.pipeline.feeds import fetch_feed

        with build_client(config) as http:
            feed = fetch_feed(feed_url.strip(), config, http, limit=int(per_feed))
        if not feed.ok:
            st.error(feed.error)
        else:
            st.write(f"Found {len(feed.entries)} entries in **{feed.feed_title}**")
            outcomes = []
            progress = st.progress(0.0)
            with session_scope() as session, build_client(config) as http:
                pipeline = Pipeline(session, config, http)
                for index, entry in enumerate(feed.entries):
                    outcomes.append(
                        pipeline.crawl_one(
                            entry.url,
                            feed_date=entry.published_raw,
                            source_label=feed.feed_title or feed_url,
                        )
                    )
                    progress.progress((index + 1) / len(feed.entries))
            progress.empty()
            _show_outcomes(outcomes)

# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------

with tab_discover:
    st.header("Discover articles by topic")

    if config.groq_api_key:
        st.caption(
            "Web search, then an LLM filters out category pages, product "
            "pages and anything that is not a readable article."
        )
    else:
        st.info(
            "No GROQ_API_KEY set, so results come back unranked — plain "
            "search order. Everything else works the same."
        )

    topic = st.text_input("Topic", placeholder="retrieval augmented generation")

    if st.button("Search", type="primary") and topic.strip():
        with st.spinner("Searching..."):
            try:
                st.session_state["candidates"] = discover_topic(topic.strip(), config)
            except SearchUnavailable as exc:
                # Search failing is not the same as a topic having no
                # articles, and saying "no results" for a network error sends
                # the user looking in the wrong place.
                st.session_state["candidates"] = []
                st.error(
                    f"Search is unavailable right now, so no candidates could "
                    f"be found.\n\n`{exc}`\n\nCrawling still works — use the "
                    "**Crawl a URL** tab."
                )

    candidates = st.session_state.get("candidates", [])
    if candidates:
        st.write(f"{len(candidates)} candidates. Pick the ones to crawl:")
        chosen: list[str] = []
        for index, candidate in enumerate(candidates):
            label = f"**{candidate.title[:80]}**"
            if candidate.score is not None:
                label += f"  ·  score {candidate.score:.2f}"
            if st.checkbox(label, key=f"cand_{index}"):
                chosen.append(candidate.url)
            st.caption(candidate.url + (f" — {candidate.reason}" if candidate.reason else ""))

        if st.button(f"Crawl {len(chosen)} selected", disabled=not chosen):
            # Note what happens next: these URLs go through the identical
            # pipeline as any other. The model's opinion does not exempt them
            # from robots.txt, rate limits or the quality gates.
            _show_outcomes(_crawl_urls(chosen))

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

with tab_report:
    st.header("Data quality report")

    if st.button("Regenerate"):
        with session_scope() as session:
            write_report(session, config)
        st.success("Report regenerated.")

    with session_scope() as session:
        report = build_report(session, config)

    if report.total_urls == 0:
        st.info("Nothing crawled yet.")
    else:
        columns = st.columns(4)
        columns[0].metric("URLs processed", report.total_urls)
        columns[1].metric("Stored", report.stored)
        columns[2].metric("Duplicates", f"{report.duplicates['pct']}%")
        columns[3].metric("Failed / junk", f"{report.extraction['pct']}%")

        columns = st.columns(3)
        columns[0].metric(
            "Missing date", f"{report.party_dates['missing_or_unparseable_pct']}%"
        )
        columns[1].metric("Mean length", f"{report.lengths['mean_chars']} chars")
        columns[2].metric("Median length", f"{report.lengths['median_chars']} chars")

        st.subheader("Every outcome")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "status": status,
                        "count": count,
                        "%": round(100 * count / report.total_urls, 1),
                    }
                    for status, count in sorted(
                        report.counts.items(), key=lambda kv: -kv[1]
                    )
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Duplicates by detection layer")
        st.dataframe(
            pd.DataFrame(
                [
                    {"layer": name, "count": data["count"], "%": data["pct"],
                     "how": data["method"]}
                    for name, data in report.duplicates["by_layer"].items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if report.party_dates["by_source"]:
            st.subheader("Where publish dates came from")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"source": source, "articles": count}
                        for source, count in report.party_dates["by_source"].items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("The shortest articles")
        st.caption("Usually the garbage. Expand and judge for yourself.")
        for item in report.shortest:
            with st.expander(
                f"{item['rank']}. {item['title'] or '(no title)'} — {item['chars']} chars"
            ):
                st.caption(item["url"])
                st.text(item["excerpt"])

        report_path = os.path.join(config.report_dir, "REPORT.md")
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as handle:
                st.download_button("Download REPORT.md", handle.read(), "REPORT.md")
