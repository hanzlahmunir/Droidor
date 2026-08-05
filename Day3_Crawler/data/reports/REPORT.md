# Data Quality Report

Generated: 2026-08-05 09:40 UTC

Every number below is computed by counting rows in `crawl_records`, not written by hand. Re-run `report` to regenerate it.

## Summary

| Metric | Value |
| --- | --- |
| URLs processed | 26 |
| Articles stored | 20 (76.9%) |
| Duplicates | 0 (0.0%) |
| Extraction failed or junk | 1 (3.8%) |
| Missing/unparseable date (of stored) | 0 (0.0%) |
| Mean article length | 8777 chars |
| Median article length | 9374 chars |

## Every outcome

Each URL gets exactly one status, so these counts partition the input and sum to the total.

| Status | Count | % |
| --- | ---: | ---: |
| `stored` | 20 | 76.9% |
| `bot_wall` | 5 | 19.2% |
| `junk` | 1 | 3.8% |
| **total** | **26** | **100%** |

## Duplicates, and how they were detected

**0 of 26 URLs (0.0%)** were duplicates.

Three independent layers, reported separately because they catch
different things and have different reliability:

| Layer | Caught | % | How |
| --- | ---: | ---: | --- |
| `url_after_normalisation` | 0 | 0.0% | Exact match on the canonical URL after normalisation (https forced, tracking params stripped, trailing slash and #fragment removed, host lowercased). |
| `content_sha256` | 0 | 0.0% | SHA-256 of the whitespace-normalised article text. Catches syndicated copies under different URLs. |
| `near_duplicate` | 0 | 0.0% | Jaccard similarity over 5-word shingles, threshold 85%. |

Highest similarity among articles we KEPT: **2.0%** (threshold 85%). 
That is comfortably below the threshold, so no kept article is a borderline call.

## Extraction failures and junk

**1 of 26 (3.8%)** either produced no text or produced text that failed a quality rule.

| Outcome | Count | % | Meaning |
| --- | ---: | ---: | --- |
| `extraction_failed` | 0 | 0.0% | Page fetched, but no article text came out of it. |
| `junk` | 1 | 3.8% | Text extracted, but it failed a quality rule. |

Which rule rejected them (one document can fail several):

| Rule | Times fired | Definition |
| --- | ---: | --- |
| `too_short` | 1 | fewer than 300 characters |
| `high_link_density` | 1 | more than 35% of characters inside <a> tags |

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
| `rss` | 19 |
| `json_ld` | 1 |

## Article length

| Metric | Characters |
| --- | ---: |
| Mean | 8777 |
| Median | 9374 |
| Shortest | 592 |
| Longest | 15568 |

Mean words per article: 1391.

## Structure retained

Clean text is not the whole job: an article stripped down to undifferentiated paragraphs has lost something too. Extraction keeps Markdown, so headings and code blocks survive.

| Metric | Value |
| --- | ---: |
| Articles with headings | 18 of 20 (90.0%) |
| Total headings kept | 139 |
| Articles with code blocks | 11 |
| Total code blocks kept | 46 |
| Total list items kept | 181 |

## The 5 shortest articles

The brief predicts these are usually garbage, so they are quoted here rather than just listed — judge for yourself.

### 1. A quote from Steve Yegge

- **592 chars**, 112 words
- URL: https://simonwillison.net/2026/Aug/4/steve-yegge
- Stored as document `#9`
- Publish date: 2026-08-04T00:42:45+00:00
- Link density: 0.10

```text
4th August 2026

> [Gas Town](https://yegge.ai/gastown.html) was intended to be reusable, but I only ever wound up using it to build itself. Gas Town fell apart at the seams with Opus 4.7. Up through 4.6 it was working brilliantly. With 4.7 we saw the introduction of the "just two more things" tic, which prevented Opus from ever converging on being ready to do real work—it always wanted to fiddle with Gas Town itself. The Opus tic never went away, so Gas Town effectively burned down. It had other problems, too, but 4.7 was the final straw.

— [Steve Yegge](https://yegge.ai/essays/the-shape-of-
...[truncated]
```

### 2. Release: llm-anthropic 0.26

- **1135 chars**, 162 words
- URL: https://simonwillison.net/2026/Aug/4/llm-anthropic
- Stored as document `#7`
- Publish date: 2026-08-04T22:00:58+00:00
- Link density: 0.08

```text
4th August 2026

[Release](https://simonwillison.net/elsewhere/release/)
[llm-anthropic 0.26](https://github.com/simonw/llm-anthropic/releases/tag/0.26)
— LLM access to models by Anthropic, including the Claude series

Includes new features enabled by [LLM 0.32](https://simonwillison.net/2026/Aug/4/new-release-of-llm/):

> - New models: `claude-fable-5`, `claude-sonnet-5`, and `claude-opus-5`. [#75](https://github.com/simonw/llm-anthropic/issues/75), [#76](https://github.com/simonw/llm-anthropic/issues/76)
> - Added server-side tools for `WebSearch`, `WebFetch`, `CodeExecution`, and `Anthropic
...[truncated]
```

### 3. Links to CSS colour palettes

- **1555 chars**, 282 words
- URL: https://jvns.ca/blog/2026/05/04/css-colour-palettes
- Stored as document `#4`
- Publish date: 2026-05-04T00:00:00+00:00
- Link density: 0.21

```text
A while back I decided to stop using Tailwind for new projects and to just write
vanilla CSS instead.

But one thing I missed about Tailwind was the [colour palette](https://v2.tailwindcss.com/docs/customizing-colors#color-palette-reference) ([here as CSS](https://gist.github.com/jvns/9e59b2cd1fe12601084ba78dded072fe)).
If I wanted a light blue I could just use `blue-100` and if I didn’t like it
maybe try `blue-200` or `blue-50`. I’m not very good with colours so it makes
a big difference to me to have a reasonable colour palette that somebody who is
better at colour than me has thought about.
...[truncated]
```

### 4. PipeNetwork/minimax-h3-mlx

- **1635 chars**, 229 words
- URL: https://simonwillison.net/2026/Aug/4/minimax-h3-mlx
- Stored as document `#8`
- Publish date: 2026-08-04T19:10:09+00:00
- Link density: 0.04

```text
**[PipeNetwork/minimax-h3-mlx](https://github.com/PipeNetwork/minimax-h3-mlx)**. MiniMax released [MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3) two days ago - they describe it as a "a general-purpose, omni-modal generative system", which in practice means it accepts text, images, audio and video and can use them to generate up to 15 second video clips with audio included.

This Python package ports it to MLX for running on Apple Silicon.

I got it running on my M5 Max MacBook Pro. I cloned the repo and ran the model like this:

```
# First download the models
uvx --from huggingface
...[truncated]
```

### 5. Learning a few things about running SQLite

- **5683 chars**, 1016 words
- URL: https://jvns.ca/blog/2026/07/17/learning-about-running-sqlite
- Stored as document `#2`
- Publish date: 2026-07-17T00:00:00+00:00
- Link density: 0.06

```text
Hello! I’ve been working on a Django site recently, and I decided to use SQLite
as the database.
When I was getting started with using SQLite as database for a website I read a [bunch](https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production)
of blog posts about how it is totally fine to use SQLite in production for a
small site and I think it *is* totally fine, but what I did not fully appreciate
is that SQLite is still a database, databases are complicated, and I do not know
a lot about operating databases.

So here are a couple of small things I’ve been learning 
...[truncated]
```

## Pages we were not allowed to read

| Reason | Count | % |
| --- | ---: | ---: |
| `bot_wall` | 5 | 19.2% |

These are detected and reported, never worked around: the brief puts anything behind a login out of scope.

## URLs we refused before fetching

None in this run.

## Per host

| Host | Attempted | Stored |
| --- | ---: | ---: |
| jvns.ca | 5 | 5 |
| simonwillison.net | 5 | 4 |
| hacks.mozilla.org | 5 | 0 |
| blog.cloudflare.com | 5 | 5 |
| research.google | 5 | 5 |
| www.claudedirectory.org | 1 | 1 |

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
