# Day 3 — Blog crawler and data-quality report

Crawls public blog articles, strips them to clean text, de-duplicates them,
parses their publish dates, and pushes them into the **Day 1 Documents API**.
Produces a data-quality report with real, recomputable numbers.

## Run it

```bash
docker compose up
```

That is the only command needed. It starts Postgres, builds and starts the
Day 1 API, and opens the crawler UI at <http://localhost:8501>.

No API key is required. (Two optional ones unlock topic discovery — see
[Optional keys](#optional-keys).)

Then crawl something:

```bash
docker compose run --rm crawler seed          # the 5 default feeds, then report
docker compose run --rm crawler crawl <url>   # one or more URLs
docker compose run --rm crawler report        # regenerate the report
docker compose run --rm crawler status        # counts + rate-limit usage
docker compose run --rm tests                 # 98 offline tests
```

Crawling is deliberately **not** started by `up`: it makes live requests to
other people's servers, and that should be an explicit act rather than a
side effect of starting the app.

> **Rebuild after editing source.** `docker compose run` reuses an existing
> image. Run `docker compose --profile cli build` first, or your change
> silently will not be in the container. This cost time twice during
> development — the tell is a test count that does not go up.

## What it does

```
URL ─► repair & normalise ─► URL dupe? ─► robots.txt ─► rate limit
    ─► FETCH (cached) ─► extract ─► blocked? ─► quality gate
    ─► content dupe? ─► near dupe? ─► publish date ─► POST to Day 1 API
```

Every URL exits with exactly one of 14 statuses, so the report's percentages
partition the input and sum to 100%.

### URL repair

The scheme is optional and a trailing slash is fine. `EXAMPLE.com/post/?utm_source=x`
becomes `https://example.com/post`. Tracking parameters (`utm_*`, `fbclid`,
`gclid`, …) are stripped; content parameters (`?p=123`) are **kept**, because
on WordPress that parameter *is* the article.

All of these normalise to one canonical URL, which is what makes duplicate
detection and Day 1's `uq_documents_url` constraint meaningful:

```
https://example.com/post      http://example.com/post
https://example.com/post/     https://EXAMPLE.com/post?utm_source=twitter
example.com/post#section-2
```

### Politeness

- **robots.txt** fetched once per host, `Crawl-delay` honoured when stricter
  than our own. Unreadable robots.txt (5xx/timeout) → refuse, don't assume.
- **Rate limits** hourly / daily / monthly, per-host and global, **persisted
  in Postgres** so a restart cannot reset an exhausted budget.
- **2s minimum** between requests to the same host.
- A real, contactable **User-Agent**.
- Nothing behind a login is fetched — detected and reported, never bypassed.

### Structure is preserved, not just text

Extraction emits **Markdown**, so an article keeps the shape its author gave
it:

| Kept | Recorded run |
| --- | ---: |
| Headings | 99 |
| Fenced code blocks, with original indentation | 54 |
| Links, as `[text](url)` | 290 |
| Blockquotes, marked with `>` | 9 lines |
| Bold and italic | 26 spans |

Code indentation matters beyond appearance — flattened Python is invalid
Python, so a reader copying a stored snippet would get an `IndentationError`.
Code text is taken from the DOM, where `<pre>` preserves whitespace, rather
than from the Markdown converter, which strips it.

Blockquote markers matter for a different reason: without them, a passage the
author was quoting from someone else reads as their own words.

None of this worked at first — the initial version stored undifferentiated
paragraphs with headings, code fences, links and quote markers all dropped.
Nine separate causes across two rounds of review, all documented in
[docs/REVIEW_NOTES.md](docs/REVIEW_NOTES.md).

One measurement note: article length and link density are computed on the
visible prose, with `[text](url)` reduced to `text`. Counting URL characters
would inflate both on the articles that cite their sources best, pushing
well-referenced writing toward the junk threshold.

The Browse tab shows each article two ways — **Formatted** (rendered, how a
reader sees it) and **Raw stored text** (exactly what is in the database, for
verification).

One known limitation, reported rather than hidden: `research.google` articles
come out with no headings, because that site puts headings and body text in
different DOM branches. The report counts structure retention and lists any
long article that lost its headings.

### Blocked content

Login walls, paywalls and bot challenges are detected and reported with a
human-readable message. They are never worked around. A paywall gets its own
status separate from a login wall, because a paywall usually *shows a teaser*
— so extraction "succeeds" and produces a plausible short article that would
otherwise quietly poison the corpus.

## The report

`data/reports/REPORT.md` and `report.json`, generated by counting rows in
`crawl_records` — never hand-written, so any reviewer can recompute them.

Results from the run recorded in this repo (25 URLs, 5 feeds):

| Metric | Value |
| --- | --- |
| URLs processed | 25 |
| Articles stored | 20 (80%) |
| Duplicates | 0 (0%) |
| Extraction failed or junk | 0 (0%) |
| Missing/unparseable date | 0 of 20 stored (0%) |
| Mean / median length | 7,812 / 8,730 chars |
| Blocked (bot wall) | 5 (20%) |
| Structure kept | 99 headings, 54 code blocks, 290 links |

Duplicates are reported by **detection layer**, not as one blended number:

| Layer | How | Catches |
| --- | --- | --- |
| URL | canonical form after normalisation | tracking-param variants, http/https, trailing slashes |
| Content | SHA-256 of normalised text | syndication under a different URL |
| Near | Jaccard over 5-word shingles, 85% | reposts with a changed intro |

All three were verified against the real crawled corpus: an exact re-crawl was
caught by SHA-256, and the same article with a new opening sentence scored
99.2% similarity.

## Optional keys

The crawl pipeline needs **no credentials**. Two keys enable topic discovery
only, and both degrade rather than fail:

| Key | Without it |
| --- | --- |
| `TAVILY_API_KEY` | search falls back to DuckDuckGo (no key needed) |
| `GROQ_API_KEY` | results come back unranked instead of LLM-filtered |

```bash
cp .env.example .env    # then fill in whichever you have
```

## Layout

```
app/
  cli.py            crawl / feed / seed / discover / report / status
  ui.py             Streamlit: browse, crawl, discover, report
  config.py         every threshold, in one place
  statuses.py       the 14 outcomes + report groupings
  report.py         builds REPORT.md and report.json from crawl_records
  discover.py       topic -> search -> LLM filter -> candidate URLs
  seeds.py          the 5 default feeds, and why each was chosen
  pipeline/
    urls.py         repair, normalise, SSRF guard
    robots.py       robots.txt cache and verdicts
    ratelimit.py    persistent rolling-window limits
    fetcher.py      HTTP + raw-HTML cache + retry
    blocks.py       login / paywall / bot-wall classification
    extract.py      trafilatura + readability cross-check + quality rules
    dates.py        the 5-rung publish-date ladder
    dedupe.py       the 3 duplicate layers
    api_client.py   talks to the Day 1 API over HTTP
    crawler.py      the orchestrator
  storage/          crawl_records + request_log
tests/              98 offline tests, no network or database needed
data/raw/           cached HTML, so extraction can be re-tuned without re-crawling
data/reports/       generated report
```

## Design notes

**Why POST to the Day 1 API instead of writing to its table.** Writing
directly would bypass the 409-on-duplicate path, the 422 validation and the
`published_at` contract — the exact behaviour worth testing. The API is also
built from `../Day1_Documents-API`, not copied, so breaking Day 1 breaks this
build visibly instead of letting a fork drift.

**Why raw HTML is cached.** Extraction was re-tuned several times while
measuring. Cached bytes mean each page was fetched once (polite) and the
report is reproducible from stored input rather than from a fresh crawl that
would return slightly different pages every time.

**Why two extractors.** trafilatura produces the output; readability-lxml runs
on the same HTML purely as a cross-check. Sharp disagreement is *evidence* of
a bad extraction, which is what makes the junk rate measured rather than
asserted.

**Why not Firecrawl.** Evaluated and rejected — see
[docs/FIRECRAWL.md](docs/FIRECRAWL.md).

**What broke during development**, and what it taught, is in
[docs/REVIEW_NOTES.md](docs/REVIEW_NOTES.md) — including a bot-wall detector
that discarded every article on a Cloudflare-fronted site, and a quality rule
that ran in the wrong direction.
