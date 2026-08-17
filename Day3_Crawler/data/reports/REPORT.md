# Data Quality Report

Generated: 2026-08-17 14:32 UTC

Every number below is computed by counting rows in `crawl_records`, not written by hand. Re-run `report` to regenerate it.

## Summary

| Metric | Value |
| --- | --- |
| URLs processed | 136 |
| Articles stored | 112 (82.4%) |
| Duplicates | 0 (0.0%) |
| Extraction failed or junk | 4 (2.9%) |
| Missing/unparseable date (of stored) | 0 (0.0%) |
| Mean article length | 8187 chars |
| Median article length | 8450 chars |

## Every outcome

Each URL gets exactly one status, so these counts partition the input and sum to the total.

| Status | Count | % |
| --- | ---: | ---: |
| `stored` | 112 | 82.4% |
| `bot_wall` | 20 | 14.7% |
| `junk` | 4 | 2.9% |
| **total** | **136** | **100%** |

## Duplicates, and how they were detected

**0 of 136 URLs (0.0%)** were duplicates.

Three independent layers, reported separately because they catch
different things and have different reliability:

| Layer | Caught | % | How |
| --- | ---: | ---: | --- |
| `url_after_normalisation` | 0 | 0.0% | Exact match on the canonical URL after normalisation (https forced, tracking params stripped, trailing slash and #fragment removed, host lowercased). |
| `content_sha256` | 0 | 0.0% | SHA-256 of the whitespace-normalised article text. Catches syndicated copies under different URLs. |
| `near_duplicate` | 0 | 0.0% | Jaccard similarity over 5-word shingles, threshold 85%. |

Highest similarity among articles we KEPT: **5.3%** (threshold 85%). 
That is comfortably below the threshold, so no kept article is a borderline call.

## Extraction failures and junk

**4 of 136 (2.9%)** either produced no text or produced text that failed a quality rule.

| Outcome | Count | % | Meaning |
| --- | ---: | ---: | --- |
| `extraction_failed` | 0 | 0.0% | Page fetched, but no article text came out of it. |
| `junk` | 4 | 2.9% | Text extracted, but it failed a quality rule. |

Which rule rejected them (one document can fail several):

| Rule | Times fired | Definition |
| --- | ---: | --- |
| `high_link_density` | 4 | more than 35% of characters inside <a> tags |
| `too_short` | 3 | fewer than 300 characters |

## Publish dates

Scope: articles that were stored (a date is only meaningful for those) — 112 articles.

| Metric | Count | % of stored |
| --- | ---: | ---: |
| Date found and parsed | 112 | 100.0% |
| **Missing or unparseable** | **0** | **0.0%** |
| — no date on the page at all | 0 | |
| — found something, could not parse it | 0 | |

Where the dates actually came from (ladder, most authoritative first):

| Source | Articles |
| --- | ---: |
| `rss` | 111 |
| `json_ld` | 1 |

## Article length

| Metric | Characters |
| --- | ---: |
| Mean | 8187 |
| Median | 8450 |
| Shortest | 337 |
| Longest | 33837 |

Mean words per article: 1286.

## Structure retained

Clean text is not the whole job: an article stripped down to undifferentiated paragraphs has lost something too. Extraction keeps Markdown, so headings and code blocks survive.

| Metric | Value |
| --- | ---: |
| Articles with headings | 84 of 112 (75.0%) |
| Total headings kept | 665 |
| Articles with code blocks | 35 |
| Total code blocks kept | 145 |
| Total list items kept | 753 |

Long articles (4,000+ chars) that came out with **no headings** — these are the ones worth inspecting:

| Article | Chars |
| --- | ---: |
| https://research.google/blog/catalyzing-scientific-impact-through-global-partnerships-and-open-resources | 4213 |

A long article with no headings usually means the page genuinely has none (a single-section post, a press release), or the extractor selected a container that excludes them. Worth opening to check which.

## The 5 shortest articles

The brief predicts these are usually garbage, so they are quoted here rather than just listed — judge for yourself.

### 1. A quote from OpenClaw (running Opus 4.6)

- **337 chars**, 57 words
- URL: https://simonwillison.net/2026/Aug/10/openclaw
- Stored as document `#52`
- Publish date: 2026-08-10T02:05:16+00:00
- Link density: 0.20

```text
10th August 2026

> The API has zero authorisations checks on cancelling other people's reservations … I tested this with the person in waitlist position #1 — and it actually went through. So you've moved from #4 to #3 already.

— [OpenClaw (running Opus 4.6)](https://www.abc.net.au/news/2026-08-10/ai-assistant-hacks-gym-website-aus-cyber-attack/107007986), hacking an Australian gym-booking website

Posted [10th August 2026](https://simonwillison.net/2026/Aug/10/) at 2:05 am
```

### 2. Sighting: Northern Gannet

- **466 chars**, 81 words
- URL: https://simonwillison.net/2026/Aug/15/sighting-391300422
- Stored as document `#40`
- Publish date: 2026-08-15T03:22:00+00:00
- Link density: 0.06

```text
This is Morris.

Morris is a local celebrity: the only known Northern Gannet (*Morus bassanus*) in the entire Pacific Ocean.

They showed up in the Farallon Islands off the coast of San Francisco [14 years ago](https://baynature.org/magazine/spring2017/atlantic-bird-makes-home-california-maybe-melting-arctic-ice/). They have since made Pillar Point harbor their home, where they are quite easy to spot: the only white bird with a yellow head, usually hanging out with the smaller black Brandt’s cormorants near the harbor sign visible from the end of the commercial pier.
```

### 3. A quote from Steve Yegge

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

### 4. A quote from John Gruber

- **640 chars**, 121 words
- URL: https://simonwillison.net/2026/Aug/8/john-gruber
- Stored as document `#58`
- Publish date: 2026-08-08T00:10:40+00:00
- Link density: 0.10

```text
8th August 2026

> Me, I try to get into the mindset of playing live music, not recording a studio album. Except when I’m writing a piece where I really want it to be an album. Those aren’t *rare*, per se, but they’re *occasional*. If I tried to make every post a hall-of-famer I’d never get anything out.
>
> I’m aiming for professionalism. I’m performing live in front of an audience — not just jamming in my garage or bedroom, fucking around. So I’m careful and concentrate. I want to hit every note, in time. But at my best I’m moving from song to song.

— [John Gruber](https://daringfireball.ne
...[truncated]
```

### 5. A quote from Florian Herrengt

- **811 chars**, 159 words
- URL: https://simonwillison.net/2026/Aug/12/florian-herrengt
- Stored as document `#47`
- Publish date: 2026-08-12T15:08:47+00:00
- Link density: 0.07

```text
12th August 2026

> But then users start to report a weird bug. It's the 4th time your team has been trying to fix it. I mean... asking AI to fix it. Unfortunately, it seems like not even Fable can figure it out.
>
> You go talk to the person who worked on this feature.
>
> "So where does the data come from?"
>
> "Hmm... actually I don't know. Let me ask Claude."
>
> You sit next to each other watching an endless wall of text appear on the screen. Neither of you has any idea whether any of it is true but Claude seems very confident. [...]
>
> This project has become so convoluted, with so many
...[truncated]
```

## Pages we were not allowed to read

| Reason | Count | % |
| --- | ---: | ---: |
| `bot_wall` | 20 | 14.7% |

These are detected and reported, never worked around: the brief puts anything behind a login out of scope.

## URLs we refused before fetching

None in this run.

## Per host

| Host | Attempted | Stored |
| --- | ---: | ---: |
| simonwillison.net | 35 | 31 |
| research.google | 35 | 35 |
| blog.cloudflare.com | 25 | 25 |
| jvns.ca | 20 | 20 |
| hacks.mozilla.org | 20 | 0 |
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
