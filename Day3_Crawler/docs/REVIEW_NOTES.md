# Review notes — why each decision, and what breaks if you change it

Every answer here cites something measured or something that actually broke
during the build, not a preference.

---

## Bugs found by running it, not by reading it

These five are the most useful part of this document: each was invisible in
code review and only appeared when the thing was actually used.

### -2. Links, code indentation and blockquotes were all being flattened

**Symptom.** Second round of review on the same article: "the hypertexts are
just simple text, the code is not indented (Python doesn't work without
indentation), and there is text which is in a box and italic but over here
it's just simple text."

**Code indentation — the serious one.** trafilatura strips leading whitespace
from every line inside a code block. Verified by diffing the source HTML
against its output: the page contains

```text
class EventQuerySet(SearchableQuerySetMixin, models.QuerySet):
    def approved(self):
        return self.filter(approved_at__isnull=False)
```

and all three lines came out flush left. For Python that is not cosmetic —
the stored snippet is syntactically invalid and raises `IndentationError` if
anyone copies it.

Fixed by taking code text from the DOM rather than the converter: `<pre>`
preserves whitespace by definition, and the raw HTML is already in hand.
Blocks are matched by their first non-blank line (the flattened and original
forms differ by exactly the whitespace being restored, so whole-block
comparison can never match), with a line-count sanity check. **An unmatched
block is left untouched** — a wrong replacement is worse than a missing
indent.

**Links.** `include_links` had been off. It could not be turned on earlier
because it emptied nine of ten headings — but that was the *self-anchor*
problem, already fixed by `unwrap_heading_anchors`. Re-measured after that
landed: 8 links restored, 10 headings intact, 0 empty. The conflict was gone
and the setting had simply never been revisited.

**Blockquotes — an attribution bug, not a formatting one.** trafilatura keeps
quoted text but drops the `>` marker, so a passage the author was quoting from
someone else becomes indistinguishable from their own words. Measured across
six real cached pages: text present in all six, marker in none. On a
link-blog post where the quotation *is* the substance, that misrepresents
both parties. Restored by matching each `<blockquote>`'s opening 60
characters back to the extracted paragraph. Quotes under 40 characters are
skipped — mis-marking ordinary prose as a quotation is worse than leaving a
real one unmarked.

**Bold and italic** turned out already to work in Markdown mode; the earlier
flattening came from the plain-text output, and no change was needed.

**A measurement trap this created.** Storing links as `[text](url)` puts every
URL into the raw string. Counting those characters would inflate both length
and link density on exactly the articles that cite their sources well —
pushing good, well-referenced writing toward the junk threshold. So length and
density are now measured on the text with link syntax reduced to its visible
label, while storage keeps the full Markdown. Guarded by a test that compares
an article with and without a long URL.

**Result across the corpus:** 290 links, 54 code blocks, 9 quoted lines and 26
bold spans preserved.

### -1. Stored articles had lost their headings and code blocks

**Symptom.** A reviewer opened a stored Julia Evans post and reported: "the
headings are missing, only the paragraphs are there, and the indentation is
not proper."

**Four independent causes**, each reproduced in isolation before being fixed:

1. **`favor_precision=True` was discarding every heading.** My flag, chosen
   to stop navigation bleeding in. Measured on the reported page: heading
   count 10 → **0**. Checked what it was actually protecting against across
   three sites — turning it off introduced no nav, footer, share buttons or
   cookie notices. It was paying a certain cost for a benefit that never
   materialised.

2. **Plain-text output dropped code fences.** `output_format="markdown"`
   restored 8 fenced blocks on that page.

3. **Headings wrapped in a self-link came out empty.** Static-site generators
   emit `<h3 id="x"><a href="#x">text</a></h3>`; with `include_links=False`
   the text is discarded and the heading renders as bare `###`. Turning
   `include_links` **on** is worse — it emptied 9 of 10 headings instead of 1.
   Fixed upstream of trafilatura by unwrapping inline tags inside headings.

4. **Inline `<code>` in a heading dropped the entire heading.**
   `<h3><code>querystring</code> is cool</h3>` produced *nothing* — not an
   empty heading, no heading at all. Confirmed with a three-case fixture:
   plain `h3` survives, `h3` containing `<code>` vanishes, `h3` that is only
   `<code>` vanishes. This is why one whole section was missing.

5. **Sentences were shredded by inline code.** trafilatura ends a paragraph
   after every inline span, so one sentence arrived as three paragraphs.
   Verified to originate in trafilatura, not our code, by inspecting its raw
   output. Repaired conservatively: a blank line is removed only when the
   line before ends mid-sentence **and** the line after starts with lowercase
   or continuing punctuation. Headings, bullets, quotes and fences are never
   joined.

6. **`normalise_text` stripped every line**, flattening nested lists and
   reindenting code. Correct for plain text, destructive for Markdown. Now
   only trailing whitespace is stripped, and lines inside `` ``` `` fences are
   left untouched.

**A near-miss worth recording.** The first version of the sentence-rejoin rule
never fired, because its "unfinished line" pattern treated a trailing backtick
as sentence-ending punctuation — and the exact input it was written for ends
in `` `querystring` ``. Caught by testing the predicate directly rather than
eyeballing the output; the rendered text looked *slightly* better for
unrelated reasons, which would have been easy to accept.

**Result:** 109 headings and 108 code fences retained across the corpus, up
from zero. One extra article now passes the quality gate (20 stored, was 19).

**What was NOT fixed, and why.** All five `research.google` articles still
have zero headings. Their markup puts headings in `div.component-intro` and
the article body in `div.blog-summary` — different DOM branches — so an
extractor that selects one content container cannot associate them. A
site-specific rule would fix it and would rot at their next redesign, so it is
**reported in REPORT.md** as a named limitation instead. The report now counts
structure retention and lists long articles that came out with no headings.

### 0. The UI shipped broken, and every automated check said it was fine

**Symptom.** Opening <http://localhost:8501> showed
`ModuleNotFoundError: No module named 'app'` at `app/ui.py` line 23.

**Cause.** `streamlit run app/ui.py` prepends the **script's** directory
(`/app/app`) to `sys.path`, not the working directory. So
`from app.config import Config` resolved against `/app/app`, where there is
no `app` package. `PYTHONPATH` was unset, so nothing put `/app` back.

**Why nothing caught it — the part worth reading.** Every check I ran was
green, and each was green for a *different* reason that masked this one:

| Check | Result | Why it missed the bug |
| --- | --- | --- |
| 98 unit tests | pass | `pytest.ini` sets `pythonpath = .` |
| CLI (`crawler seed`) | works | run as `python -m app.cli`, so cwd is on `sys.path` |
| `exec ui python -c "import app.config"` | works | cwd is `/app`, not `/app/app` |
| `curl localhost:8501` | HTTP 200 | Streamlit *started* fine |
| container health | healthy | the process is alive and serving |
| "exercise all UI code paths" | pass | I imported `app.ui`'s dependencies **in the wrong context** |

That last row is the real lesson. I ran the UI's imports and DataFrame
construction inside the container and declared "ALL UI PATHS OK" — but from
`/app`, which is not where Streamlit runs them from. The check looked
thorough and tested the wrong thing.

Streamlit compounds it by rendering the traceback **into the page** rather
than exiting, so the container stays healthy and the logs stay clean. The
only way to see the failure was to open the page in a browser, which no
automated check did.

**Fix.** Three layers, because one was clearly not enough:

1. `ENV PYTHONPATH=/app` in the Dockerfile — the actual fix.
2. `entrypoint.sh` verifies `import app.ui` **from `/app/app`**, reproducing
   Streamlit's import context, and refuses to start on failure. A broken
   image now dies loudly instead of serving a broken page.
3. `tests/test_ui_imports.py` runs the import in a **subprocess** with a
   controlled cwd and `PYTHONPATH` — in-process assertions cannot catch this,
   because pytest has already fixed `sys.path` by the time they run. One test
   asserts the bug still reproduces without `PYTHONPATH`, so the Dockerfile
   line cannot be deleted as redundant.

**Generalisable rule:** for a web UI, "the process started" and "HTTP 200"
are not evidence it works. Something has to render the page. And when
verifying an entry point, reproduce *its* execution context — cwd, argv,
environment — not a convenient approximation of it.

---

The four below were found by pointing the crawler at real websites.

### 1. The bot-wall detector discarded every article on a Cloudflare site

**Symptom.** All five Mozilla Hacks articles were rejected as `bot_wall`.

**Cause.** `"cdn-cgi/challenge-platform"` was in the marker list. Fetching one
of those pages directly returned **HTTP 200 with a normal 43 KB article**, and
the marker appeared at offset 43059 — inside Cloudflare's passive telemetry
beacon (`window.__CF$cv$params`), which Cloudflare injects into *every* page
it serves. The match detected "this site uses Cloudflare", not "Cloudflare is
blocking you". `"ray id:"` had the same defect — it appears in ordinary
Cloudflare footers.

**Fix.** Removed both markers, and added a structural veto:
`_looks_like_a_real_article()`. A marker now only counts if the page *also*
behaves like a wall — a non-success status, or under 1,200 characters of
extracted text. A 200 response carrying a full article did not block us,
whatever strings its analytics scripts contain.

**Lesson.** A substring match against a whole HTML document is evidence, not
proof. Vendor strings appear on normal pages.

**What breaks if you change it:** raise `_REAL_ARTICLE_CHARS` too high and
verbose block pages get stored as articles; remove the veto and one
over-broad marker silently deletes every article on a large slice of the web.

### 2. The extractor-disagreement rule ran in the wrong direction

**Symptom.** All five Google Research articles rejected as `junk`:
"extractors disagree on length (7373 vs 1851 chars)".

**Cause.** The rule fired on *any* large disagreement. Reading the stored text
showed trafilatura's 7,373 characters were clean and complete — readability,
the cruder algorithm, had given up early. The rule was blaming the wrong
extractor.

**Fix.** Disagreement now only counts when the **primary is the shorter one**
(`chars < secondary_chars`), which is the only case that is evidence against
the output we actually keep.

**What breaks if you change it:** drop the direction check and you reject
every long, well-extracted article on any site readability handles poorly.

### 3. Re-crawling a known URL crashed the run

**Symptom.** `IntegrityError: duplicate key value violates unique constraint
"uq_crawl_records_canonical_url"`.

**Cause.** The "every URL gets a record" invariant inserted a second row for a
URL already in the table. Normalisation was working perfectly — the dirty URL
`http://blog.cloudflare.com/bgp-origin-attribute/?utm_source=twitter&fbclid=xyz`
collapsed onto the stored canonical and dedupe correctly identified record #19
— and then it tried to INSERT.

**Fix.** The URL-duplicate branch returns the **existing** record without
inserting. Inserting was also wrong on the merits: a second row would
double-count that article in every percentage, so the report's numbers would
drift upward every time anyone re-ran a crawl.

**What breaks if you change it:** the unique constraint fires again, and the
report's denominator grows with usage.

### 4. Three of five feeds were lost to transient DNS

**Symptom.** `could not fetch feed: [Errno -5] No address associated with
hostname` on three feeds; retrying by hand seconds later worked every time.

**Cause and fix.** Measured rather than guessed: resolution succeeded 10/10
once the container had settled, so the failures were **bursty and clustered
at container start** — exactly when `seed` fires all five feed requests. A
3-attempt retry with 1s/2s backoff was not enough (the second run lost three
feeds again). Feeds now get 5 attempts with 2s/4s/8s/16s backoff.

Feeds are more patient than articles on purpose: a failed feed loses every
article behind it.

---

## Design decisions

### Why POST to the Day 1 API instead of writing to its table

Both write to the same Postgres. Writing directly would be fewer moving parts
and would *bypass the 409-on-duplicate path, the 422 validation and the
`published_at` contract* — the exact behaviour worth exercising. Two writers
to one table also means two places enforcing invariants.

*Breaks if changed:* Day 1's guarantees become untested, and the crawler can
insert rows the API would have rejected.

### Why `published_at` needed a new column instead of reusing `created_at`

They answer different questions. `created_at` is when *we* stored the row;
`published_at` is when the *author* published. Verified live: an article shows
`published_at` 2019-03-14 and `created_at` 2026-07-30.

`created_at` can never be missing or unparseable because we generate it — so
if it were the answer, "% with a missing or unparseable date" would be 0% by
construction and the whole metric would be meaningless.

Nullable on purpose: `NULL` means "we looked and could not find one", which is
a real state the report counts. `NOT NULL` would force the crawler to invent a
value and destroy the signal.

### Why raw HTML is cached to disk

Two reasons, both load-bearing. **Politeness:** extraction was re-tuned four
times while measuring; cached bytes mean each page was fetched once instead of
once per iteration. **Reproducibility:** the report is computed from stored
input, so re-running gives the same numbers. Regenerating from a fresh crawl
would differ every time — pages change, some are down — making the figures
unverifiable.

### Why two extractors when only one's output is used

The brief asks for "% of pages where extraction failed or returned junk" — a
real number. With one extractor there is nothing to compare against, so junk
could only be *asserted*. readability-lxml runs on the same HTML with a
genuinely different algorithm; sharp disagreement is *evidence*. That is what
makes the number measured.

### Why three duplicate layers reported separately

They catch different things and have different reliability. URL and content
hashing are exact and need no threshold. Near-duplicate is a judgement call
with a tunable number — so its matches are stored *with* the similarity score,
and the report shows the highest score among articles we **kept**, so a
reviewer can see whether the threshold was doing real work.

Blending them into one "% duplicates" would hide which mechanism did the work.

### Why Jaccard on shingles rather than MinHash

MinHash exists to avoid all-pairs comparison at millions of documents. At
~20-100 articles, exact Jaccard is instant and has no approximation error;
MinHash would add a false-negative rate to save time we are not spending. The
shingle sets computed here are exactly what MinHash would consume, so the
upgrade is local to one file.

### Why word shingles rather than a bag of words

Two articles on one topic share most of their vocabulary while being entirely
different pieces of writing. Requiring runs of five consecutive words means a
high score reflects **copied phrasing**, not a shared subject. Tested:
`"the cat sat on the mat while the dog watched"` vs the same words reordered
scores below 0.3.

### Why rate limits live in Postgres rather than memory

An in-process counter resets on restart, so `docker compose restart` would
silently reset an exhausted daily budget. Verified: `crawler status` in a
fresh `run --rm` container reported 25/300 for the hour, counting requests
made by an earlier container.

Also **rolling windows, not calendar buckets**: with a calendar-hour counter
and a 60/hour limit, you can fire 60 requests at 10:59 and 60 more at 11:00 —
120 in two minutes without ever exceeding the limit.

### Why robots.txt failures are fail-closed, but a 404 is fail-open

A missing robots.txt means no restrictions — that is the standard's own
default. A 5xx or a timeout means we *could not read the rules*, which is not
the same as permission. Different causes, different answers.

### Why the SSRF guard resolves DNS instead of blocklisting names

A name blocklist is trivially bypassed: an attacker controls DNS for their own
domain and can point `evil.example.com` at `127.0.0.1`. Only the resolved
address tells the truth. Uses `ip.is_global`, which covers loopback,
link-local (including the `169.254.169.254` cloud metadata endpoint), private
ranges, multicast and reserved in one property rather than a hand-maintained
CIDR list that will miss one.

Day 2's peer review found this exact hole in the co-intern's `fetch_url`, and
the first pass at that review wrongly called it safe because the metadata
address "errored" — but only because nothing was listening on that laptop. On
a cloud VM the same request returns IAM credentials. So the tests assert on
literal IPs whose class is fixed, testing the **guard** rather than the
environment.

*Known limitation, stated rather than hidden:* this is a check-then-connect
race. The name could resolve to a public IP here and a private one when httpx
resolves it again. Closing it fully means pinning the connection to the
validated IP, which httpx does not expose cleanly.

### Why the URL normaliser keeps `?p=123` but strips `?utm_source=x`

`utm_*` identifies the campaign that sent a visitor. `?p=123` on WordPress
**is the article** — stripping it turns every URL on the site into the
homepage, and then the duplicate layer merges them all into one document.
This is the classic over-aggressive-normalisation bug and it has a test.

Path case is preserved while host case is lowered: hostnames are
case-insensitive per RFC 3986, paths are not. Lowercasing `/Blog/My-Post`
404s on any case-sensitive server.

### Why `create_all` here when Day 1 insists on migrations

Day 1's `documents` table is a published contract with external readers. These
two tables are internal, disposable bookkeeping — if the schema changes, the
right action is to drop and re-crawl. An Alembic setup would be ceremony
implying a stability guarantee this data does not have. The table the crawler
*writes to* is still migration-managed, in Day 1, where the rule belongs.

### Why `docker compose up` does not start a crawl

Crawling makes live requests to other people's servers. That should be an
explicit act, not a side effect of starting the app. `up` gives you a working
UI; `run --rm crawler seed` crawls.

### Why the date ladder records which rung won

"83% had dates" is much less useful than a table showing where they came
from. The measurement changed the code: re-running the ladder over the 20
cached pages **with the RSS hint removed** showed 8 of 20 producing no date at
all. Inspecting those showed most carried only
`<meta property="og:updated_time" content="1785359721">` — a bare Unix epoch,
which dateutil cannot parse and which was not in the key list. Adding both
dropped no-date from 8/20 to **3/20**.

The epoch path shares `_validate()` with the normal path, so it cannot skip
the plausibility window.

### Why implausible dates are rejected rather than stored

A "successfully parsed" 1970 or 2099 date is worse than none: it looks valid,
it sorts, and nothing downstream flags it. 1970 is usually a CMS with an empty
field; a future date is usually a scheduled-post placeholder. Both are
reported as unparseable, **with the raw string kept** as evidence.

---

## Likely review questions

**"Your duplicate rate is 0%. Does dedupe work?"**
Yes — 0% is the honest number for 25 URLs from 5 feeds that do not syndicate
from each other. All three layers were verified against the real corpus:
re-crawling a stored URL with tracking params was caught by the URL layer
(record #19); the SHA-256 layer caught an exact re-check; and the same article
with a new opening sentence scored **99.2%** on the near layer. Unrelated text
correctly scored as non-duplicate.

**"100% of dates came from RSS. Is the rest of the ladder dead code?"**
It is untested *by that run*, which is why it was measured separately. With
the RSS hint removed, the same 20 pages resolve via `json_ld` (5),
`meta_article` (5), `time_element` (5) and `text_pattern` (2). Every rung
fires on real pages.

**"20% of your corpus is bot-walled. Isn't that a failure?"**
It is a correctly-reported outcome. Mozilla Hacks returns 403 to the container
while returning 200 for the identical URL and User-Agent from the host — an
IP-reputation block, not a login wall. That distinction is why 403 without a
login form is classified as `bot_wall` rather than `login_required`:
reporting it as "requires a login" would be a false statement in the report
and would send someone hunting for credentials that do not exist.

**"Why is the mean length below the median?"**
It is not here (8,031 vs 8,941) — the mean is *lower*, meaning short articles
pull it down. Both are reported precisely so that skew is visible. Three of
the five shortest are Simon Willison link-blog quote posts, which are
genuinely short by design rather than extraction failures — visible in the
report, which quotes them in full.
