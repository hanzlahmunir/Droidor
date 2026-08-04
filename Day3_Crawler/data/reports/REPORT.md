# Data Quality Report

Generated: 2026-08-04 15:41 UTC

Every number below is computed by counting rows in `crawl_records`, not written by hand. Re-run `report` to regenerate it.

## Summary

| Metric | Value |
| --- | --- |
| URLs processed | 26 |
| Articles stored | 20 (76.9%) |
| Duplicates | 0 (0.0%) |
| Extraction failed or junk | 1 (3.8%) |
| Missing/unparseable date (of stored) | 0 (0.0%) |
| Mean article length | 8407 chars |
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

Highest similarity among articles we KEPT: **1.8%** (threshold 85%). 
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
| Mean | 8407 |
| Median | 9374 |
| Shortest | 410 |
| Longest | 15568 |

Mean words per article: 1339.

## Structure retained

Clean text is not the whole job: an article stripped down to undifferentiated paragraphs has lost something too. Extraction keeps Markdown, so headings and code blocks survive.

| Metric | Value |
| --- | ---: |
| Articles with headings | 16 of 20 (80.0%) |
| Total headings kept | 131 |
| Articles with code blocks | 10 |
| Total code blocks kept | 41 |
| Total list items kept | 179 |

## The 5 shortest articles

The brief predicts these are usually garbage, so they are quoted here rather than just listed — judge for yourself.

### 1. Don’t be a meat proxy

- **410 chars**, 76 words
- URL: https://simonwillison.net/2026/Aug/3/dont-be-a-meat-proxy
- Stored as document `#7`
- Publish date: 2026-08-03T23:45:04+00:00
- Link density: 0.06

```text
**[Don't be a meat proxy](https://gruhn.me/blog/2026-08-03/)** ([via](https://lobste.rs/s/hfbqr3/don_t_be_meat_proxy#c_svolls "Lobste.rs")) Niklas Gruhn coins an excellent new term - **meat proxy** - for people who blindly copy and paste the output of AI systems to their peers.

> By all means, prompt AI. But don't just relay the output. Read it, understand it, validate it, and then write a response in your own words (a decent certificate that you've done the prior steps). Making that effort is value you can add.
```

### 2. A quote from Steve Yegge

- **539 chars**, 102 words
- URL: https://simonwillison.net/2026/Aug/4/steve-yegge
- Stored as document `#6`
- Publish date: 2026-08-04T00:42:45+00:00
- Link density: 0.04

```text
> [Gas Town](https://yegge.ai/gastown.html) was intended to be reusable, but I only ever wound up using it to build itself. Gas Town fell apart at the seams with Opus 4.7. Up through 4.6 it was working brilliantly. With 4.7 we saw the introduction of the "just two more things" tic, which prevented Opus from ever converging on being ready to do real work—it always wanted to fiddle with Gas Town itself. The Opus tic never went away, so Gas Town effectively burned down. It had other problems, too, but 4.7 was the final straw.

— [Steve Yegge](https://yegge.ai/essays/the-shape-of-things-to-come/),
...[truncated]
```

### 3. Comment: Devtools must be open source (exe.dev)

- **1082 chars**, 202 words
- URL: https://simonwillison.net/2026/Aug/3/devtools-must-be-open-source-exedev
- Stored as document `#8`
- Publish date: 2026-08-03T15:30:38+00:00
- Link density: 0.06

```text
[Comment](https://simonwillison.net/elsewhere/comment/) [My comment](https://news.ycombinator.com/item?id=49156111#49156719) on [Devtools must be open source (exe.dev)](https://news.ycombinator.com/item?id=49156111) — Hacker News

One of the arguments for open source software for end-users has always been the freedom to examine and modify how that software works.

The reality for most people - even expert programmers - has been that the freedom is more about being able to lean on *other people* to do that. Most people can't justify the time commitment needed to read and then modify the code fo
...[truncated]
```

### 4. Release: condense-json 1.0

- **1244 chars**, 207 words
- URL: https://simonwillison.net/2026/Aug/2/condense-json
- Stored as document `#9`
- Publish date: 2026-08-02T22:19:59+00:00
- Link density: 0.01

```text
I'm trying to get braver at releasing 1.0 versions. This little library is a year and a half old now - I've applied some sensible and non-disruptive fixes and shipped the big 1.0 for it.

Here's an example of what it can do, lifted from the README:

```
{
  "foo": {
    "bar": {
      "string": "This is a string with foxes in it",
      "nested": {
        "more": ["Here is a string", "another with foxes in it too"]
      }
    }
  }
}
```

Combine that with a replacements object:

```
{"1": "with foxes in it"}
```

And `condense_json(input_json, replacements)` produces the following:

```
{
 
...[truncated]
```

### 5. Links to CSS colour palettes

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
