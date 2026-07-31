# Data Quality Report

Generated: 2026-07-31 15:47 UTC

Every number below is computed by counting rows in `crawl_records`, not written by hand. Re-run `report` to regenerate it.

## Summary

| Metric | Value |
| --- | --- |
| URLs processed | 25 |
| Articles stored | 20 (80.0%) |
| Duplicates | 0 (0.0%) |
| Extraction failed or junk | 0 (0.0%) |
| Missing/unparseable date (of stored) | 0 (0.0%) |
| Mean article length | 7812 chars |
| Median article length | 8730 chars |

## Every outcome

Each URL gets exactly one status, so these counts partition the input and sum to the total.

| Status | Count | % |
| --- | ---: | ---: |
| `stored` | 20 | 80.0% |
| `bot_wall` | 5 | 20.0% |
| **total** | **25** | **100%** |

## Duplicates, and how they were detected

**0 of 25 URLs (0.0%)** were duplicates.

Three independent layers, reported separately because they catch
different things and have different reliability:

| Layer | Caught | % | How |
| --- | ---: | ---: | --- |
| `url_after_normalisation` | 0 | 0.0% | Exact match on the canonical URL after normalisation (https forced, tracking params stripped, trailing slash and #fragment removed, host lowercased). |
| `content_sha256` | 0 | 0.0% | SHA-256 of the whitespace-normalised article text. Catches syndicated copies under different URLs. |
| `near_duplicate` | 0 | 0.0% | Jaccard similarity over 5-word shingles, threshold 85%. |

Highest similarity among articles we KEPT: **15.6%** (threshold 85%). 
That is comfortably below the threshold, so no kept article is a borderline call.

## Extraction failures and junk

**0 of 25 (0.0%)** either produced no text or produced text that failed a quality rule.

| Outcome | Count | % | Meaning |
| --- | ---: | ---: | --- |
| `extraction_failed` | 0 | 0.0% | Page fetched, but no article text came out of it. |
| `junk` | 0 | 0.0% | Text extracted, but it failed a quality rule. |

## Publish dates

Scope: articles that were stored (a date is only meaningful for those) — 20 articles.

| Metric | Count | % of stored |
| --- | ---: | ---: |
| Date found and parsed | 20 | 100.0% |
| **Missing or unparseable** | **0** | **0.0%** |
| — no date on the page at all | 0 | |
| — found something, could not parse it | 0 | |

Where the dates actually came from (ladder, most authoritative first):

| Source | Articles |
| --- | ---: |
| `rss` | 20 |

## Article length

| Metric | Characters |
| --- | ---: |
| Mean | 7812 |
| Median | 8730 |
| Shortest | 859 |
| Longest | 18928 |

Mean words per article: 1202.

## Structure retained

Clean text is not the whole job: an article stripped down to undifferentiated paragraphs has lost something too. Extraction keeps Markdown, so headings and code blocks survive.

| Metric | Value |
| --- | ---: |
| Articles with headings | 10 of 20 (50.0%) |
| Total headings kept | 99 |
| Articles with code blocks | 9 |
| Total code blocks kept | 54 |

Long articles (4,000+ chars) that came out with **no headings** — these are the ones worth inspecting:

| Article | Chars |
| --- | ---: |
| https://research.google/blog/symptomai-towards-a-conversational-ai-agent-for-everyday-symptom-assessment | 11018 |
| https://research.google/blog/towards-demystifying-the-creativity-of-diffusion-models | 8924 |
| https://research.google/blog/sensorfm-towards-a-general-intelligence-and-interface-for-wearable-health-data | 8536 |
| https://research.google/blog/towards-a-quantum-computer-that-learns-from-its-errors | 7094 |
| https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence | 6250 |

Known cause for `research.google`: its headings sit in a different DOM branch (`div.component-intro`) from its article body (`div.blog-summary`), so an extractor that selects one content container cannot associate them. Reported rather than worked around with a site-specific rule.

## The 5 shortest articles

The brief predicts these are usually garbage, so they are quoted here rather than just listed — judge for yourself.

### 1. A quote from Bruce Schneier

- **859 chars**, 142 words
- URL: https://simonwillison.net/2026/Jul/30/bruce-schneier
- Stored as document `#9`
- Publish date: 2026-07-30T18:25:26+00:00
- Link density: 0.33

```text
30th July 2026

> The writing assignments I give my students are gym tasks, not work tasks. I ask them to write policy memos not because the world needs more policy memos. I assign them because the very act of writing, which includes thinking and outlining and drafting and editing, making and criticizing and revising arguments, will help develop the critical thinking skills they will need in their future careers. And without this constant mental exercise, those skills will atrophy. Employers are

[already noticing].

— [Bruce Schneier](https://www.schneier.com/blog/archives/2026/07/should-you-
...[truncated]
```

### 2. Links to CSS colour palettes

- **1453 chars**, 258 words
- URL: https://jvns.ca/blog/2026/05/04/css-colour-palettes
- Stored as document `#4`
- Publish date: 2026-05-04T00:00:00+00:00
- Link density: 0.10

```text
# Links to CSS colour palettes

A while back I decided to stop using Tailwind for new projects and to just write vanilla CSS instead.

But one thing I missed about Tailwind was the [colour palette](https://v2.tailwindcss.com/docs/customizing-colors#color-palette-reference) ([here as CSS](https://gist.github.com/jvns/9e59b2cd1fe12601084ba78dded072fe)).
If I wanted a light blue I could just use `blue-100` and if I didn’t like it
maybe try `blue-200` or `blue-50` . I’m not very good with colours so it makes
a big difference to me to have a reasonable colour palette that somebody who is
better at 
...[truncated]
```

### 3. Release: llm-chat-completions-server 0.1a0

- **1557 chars**, 227 words
- URL: https://simonwillison.net/2026/Jul/30/llm-chat-completions-server
- Stored as document `#10`
- Publish date: 2026-07-30T15:43:16+00:00
- Link density: 0.21

```text
30th July 2026

[Release](https://simonwillison.net/elsewhere/release/)

[llm-chat-completions-server 0.1a0](https://github.com/simonw/llm-chat-completions-server/releases/tag/0.1a0)— LLM plugin to serve an OpenAI Chat Completions API endpoint

A key goal of the new content-addressable logs [in LLM 0.32rc1](https://simonwillison.net/2026/Jul/30/llm-rc1/) was being able to support OpenAI Chat Completion style requests where each incoming message extends the previous conversation, like this:

```
curl http://localhost:8002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
   
...[truncated]
```

### 4. Release: llm 0.32rc2

- **1601 chars**, 268 words
- URL: https://simonwillison.net/2026/Jul/30/llm-rc2
- Stored as document `#8`
- Publish date: 2026-07-30T22:52:06+00:00
- Link density: 0.21

```text
30th July 2026

Hot on the heels of [RC1](https://simonwillison.net/2026/Jul/30/llm-rc1/), this fixes a dependency issue and also adds two neat new features:

> - The default model for users who have not set their own default is now [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna). It was previously [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini). Luna is a much better and more recent model, albeit slightly more expensive - $0.20 per million input tokens and $1.20 per million output tokens, compared to $0.15/$0.60 for 4o mini. You can switch b
...[truncated]
```

### 5. Advancing the price-performance frontier with GPT‑5.6

- **1977 chars**, 301 words
- URL: https://simonwillison.net/2026/Jul/30/luna-price-drop
- Stored as document `#6`
- Publish date: 2026-07-30T23:58:42+00:00
- Link density: 0.20

```text
30th July 2026 - Link Blog

** Advancing the price-performance frontier with GPT‑5.6** (

[via](https://news.ycombinator.com/item?id=49112867)) Huge price drop from OpenAI today: GPT-5.6 Terra got a 20% reduction, and GPT-5.6 Luna got a massive 80% drop.

OpenAI credit 5.6 Sol with enabling this: in [How GPT‑5.6 fuses frontier intelligence with frontier efficiency](https://openai.com/index/gpt-5-6-frontier-intelligence-efficiency/) they describe using 5.6 Sol to optimize load balancing, and more impressively to optimize inference itself:

> We also used GPT‑5.6 Sol to optimize the model’s forw
...[truncated]
```

## Pages we were not allowed to read

| Reason | Count | % |
| --- | ---: | ---: |
| `bot_wall` | 5 | 20.0% |

These are detected and reported, never worked around: the brief puts anything behind a login out of scope.

## URLs we refused before fetching

None in this run.

## Per host

| Host | Attempted | Stored |
| --- | ---: | ---: |
| jvns.ca | 5 | 5 |
| simonwillison.net | 5 | 5 |
| hacks.mozilla.org | 5 | 0 |
| blog.cloudflare.com | 5 | 5 |
| research.google | 5 | 5 |

## Thresholds these numbers were measured against

| Setting | Value |
| --- | --- |
| Minimum article length | 300 chars |
| Maximum link density | 0.35 |
| Extractor agreement floor | 0.5 |
| Near-duplicate threshold | 0.85 |
| Shingle size | 5 words |
| Plausible date range | 1995 to today+2d |

Changing any of these changes the numbers above, which is why they are stated here rather than buried in the code.
