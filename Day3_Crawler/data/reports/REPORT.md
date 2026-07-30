# Data Quality Report

Generated: 2026-07-30 11:51 UTC

Every number below is computed by counting rows in `crawl_records`, not written by hand. Re-run `report` to regenerate it.

## Summary

| Metric | Value |
| --- | --- |
| URLs processed | 25 |
| Articles stored | 19 (76.0%) |
| Duplicates | 0 (0.0%) |
| Extraction failed or junk | 1 (4.0%) |
| Missing/unparseable date (of stored) | 0 (0.0%) |
| Mean article length | 8031 chars |
| Median article length | 8941 chars |

## Every outcome

Each URL gets exactly one status, so these counts partition the input and sum to the total.

| Status | Count | % |
| --- | ---: | ---: |
| `stored` | 19 | 76.0% |
| `bot_wall` | 5 | 20.0% |
| `junk` | 1 | 4.0% |
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

Highest similarity among articles we KEPT: **0.5%** (threshold 85%). 
That is comfortably below the threshold, so no kept article is a borderline call.

## Extraction failures and junk

**1 of 25 (4.0%)** either produced no text or produced text that failed a quality rule.

| Outcome | Count | % | Meaning |
| --- | ---: | ---: | --- |
| `extraction_failed` | 0 | 0.0% | Page fetched, but no article text came out of it. |
| `junk` | 1 | 4.0% | Text extracted, but it failed a quality rule. |

Which rule rejected them (one document can fail several):

| Rule | Times fired | Definition |
| --- | ---: | --- |
| `too_short` | 1 | fewer than 300 characters |

## Publish dates

Scope: articles that were stored (a date is only meaningful for those) — 19 articles.

| Metric | Count | % of stored |
| --- | ---: | ---: |
| Date found and parsed | 19 | 100.0% |
| **Missing or unparseable** | **0** | **0.0%** |
| — no date on the page at all | 0 | |
| — found something, could not parse it | 0 | |

Where the dates actually came from (ladder, most authoritative first):

| Source | Articles |
| --- | ---: |
| `rss` | 19 |

## Article length

| Metric | Characters |
| --- | ---: |
| Mean | 8031 |
| Median | 8941 |
| Shortest | 514 |
| Longest | 18183 |

Mean words per article: 1253.

## The 5 shortest articles

The brief predicts these are usually garbage, so they are quoted here rather than just listed — judge for yourself.

### 1. A quote from D. Richard Hipp

- **514 chars**, 90 words
- URL: https://simonwillison.net/2026/Jul/29/d-richard-hipp
- Stored as document `#6`
- Publish date: 2026-07-29T21:15:21+00:00
- Link density: 0.07

```text
29th July 2026
Years ago, we didn’t have SQL. There were people whose job was to generate software that would query large data sets. Their job title was COBOL programmer.
Then SQL comes along—I’m simplifying this only a little bit—and it gives you this convenient way so people could just specify. With a very simple specification, you can generate all of that code that you had to pay the expensive COBOL programmer to do before.
That didn’t mean programmers went away. It just meant the job changed a little bit.
```

### 2. A quote from Matthew Green

- **746 chars**, 126 words
- URL: https://simonwillison.net/2026/Jul/29/matthew-green
- Stored as document `#8`
- Publish date: 2026-07-29T18:18:15+00:00
- Link density: 0.08

```text
29th July 2026
Right now we’re in the midst of a historic transition from traditional public-key algorithms based on EC-based cryptography and RSA, moving over to new post-quantum algorithms based on novel problems. This is why there are so many standards like HAWK being considered. If there was ever a perfect time for a massive new public cryptanalysis capability to come on line, we’re in it. So unless AIs succeed in undermining all of our hard problems altogether (or we live in Impagliazzo’s Minicrypt) then this could not be a better time for AI to get good at cryptanalysis. In the best case
...[truncated]
```

### 3. AI Worming through Word

- **1171 chars**, 187 words
- URL: https://simonwillison.net/2026/Jul/29/ai-worming-through-word
- Stored as document `#7`
- Publish date: 2026-07-29T18:43:03+00:00
- Link density: 0.09

```text
29th July 2026 - Link Blog
AI Worming through Word (via) Neat new prompt injection variant by Håkon Måløy, who found a way to upgrade prompt injection attacks against Microsoft Word to full self-replicating worms:
An attacker places hidden instructions in a document that is later used as source material in Copilot for Word. Copilot may interpret those instructions as part of the user’s request, causing it to manipulate the document being drafted or edited. Copilot may then also copy the hidden instructions into the resulting document, turning that document into a new carrier. If the carrier is
...[truncated]
```

### 4. Discovering cryptographic weaknesses with Claude

- **1290 chars**, 219 words
- URL: https://simonwillison.net/2026/Jul/28/discovering-cryptographic-weaknesses-with-claude
- Stored as document `#9`
- Publish date: 2026-07-28T22:45:37+00:00
- Link density: 0.12

```text
28th July 2026 - Link Blog
Discovering cryptographic weaknesses with Claude (via) The best part of this article (here's the repo) about how Anthropic researchers used Claude Mythos to find mathematical flaws in both HAWK and a weaker version of AES ("neither of these results has a practical impact on today’s computer systems") is the prompts that they shared, spelling mistakes included:
the models tend to think it is impossible to solve so they don't try they need a good amount of prompting.
why not do aes-128 r7? the whole point is to find something better than existing approaches.
no again t
...[truncated]
```

### 5. Links to CSS colour palettes

- **1334 chars**, 250 words
- URL: https://jvns.ca/blog/2026/05/04/css-colour-palettes
- Stored as document `#4`
- Publish date: 2026-05-04T00:00:00+00:00
- Link density: 0.11

```text
A while back I decided to stop using Tailwind for new projects and to just write vanilla CSS instead.
But one thing I missed about Tailwind was the colour palette (here as CSS).
If I wanted a light blue I could just use blue-100
and if I didn’t like it
maybe try blue-200
or blue-50
. I’m not very good with colours so it makes
a big difference to me to have a reasonable colour palette that somebody who is
better at colour than me has thought about.
But I’m also a little tired of those Tailwind colours, so I asked on Mastodon today what other colour palettes were out there. And then a friend sai
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
| simonwillison.net | 5 | 4 |
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
