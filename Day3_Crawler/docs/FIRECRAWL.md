# Firecrawl: evaluated, not used

Firecrawl was considered for the scraping layer, specifically because it is
reputed to handle CAPTCHAs and bot checks automatically. It was rejected.
This note records why, so the decision can be re-examined if the facts change.

## 1. The anti-bot capability is not in the open-source product

Firecrawl core is AGPL-3.0 and self-hostable with Docker Compose. But the
part that motivated the evaluation is not in it. The proprietary anti-bot and
proxy layer ("Fire-engine"), residential IP rotation, the `/agent` endpoint
and the browser sandbox are **cloud-only and closed-source**.

Self-hosting Firecrawl gives you Playwright with some stealth options — which
is roughly what you get by writing it yourself. So "use Firecrawl to handle
CAPTCHAs" resolves to "pay for the hosted API", not "run their container".

## 2. Even the hosted product is not a CAPTCHA solution

An independent Proxyway benchmark (late 2025) measured Firecrawl at a
**33.69% success rate at 2 req/s** against protected sites, dropping to
**26.69% at 10 req/s**. That is a modestly better fetcher, not a way through
bot walls. Adopting it would have imported a dependency without delivering
the capability it was being adopted for.

## 3. It breaks the one-command rule

The hosted API needs an account and an API key. The project's entry point is
`docker compose up` with no credentials required. Firecrawl would make that
"sign up for a third-party service, get a key, then run" — for a crawler that
otherwise needs no credentials at all.

## 4. It would hollow out the part being graded

Day 3 is assessed on extraction quality and data quality. If a SaaS does the
extraction, then "how do you strip nav and footers?" is answered by "I POST
the URL to someone else", and the measured junk rate becomes a measurement of
their product. There would be no line to defend in review.

## What was built instead

`httpx` + `trafilatura`, with `readability-lxml` as an independent
cross-check. trafilatura is the current state of the art for boilerplate
removal and is what extraction benchmarks measure against.

The capability Firecrawl was wanted for — dealing with bot walls — was
addressed by **detecting and reporting them as first-class outcomes** rather
than defeating them. That is also the correct answer to the brief, which puts
anything behind a login out of scope.

## If this is revisited

The fetcher sits behind a small interface (`Fetcher.fetch` returning a
`FetchResult`), so a Firecrawl backend could be added without touching
extraction, dedupe, dates or the report. The trigger for reconsidering would
be a corpus where a large share of target sites are genuinely unreachable —
and the honest fix there is usually to pick different sources, not to escalate
an arms race with someone's WAF.

## Sources

- <https://www.firecrawl.dev/pricing> — free tier is 1,000 credits/month;
  1 credit per page scraped
- <https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md>
- <https://webscraping.ai/faq/firecrawl/is-firecrawl-open-source-and-can-i-self-host-it>
  — self-hosted vs cloud feature split
- <https://fastcrw.com/blog/firecrawl-vs-crawl4ai-vs-crw> — cites the Proxyway
  success-rate benchmark
