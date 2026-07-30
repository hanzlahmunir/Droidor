"""Topic -> candidate article URLs, via web search plus an LLM filter.

WHY THIS EXISTS ALONGSIDE URL AND FEED INPUT.
A URL says "fetch this specific thing". A topic says "go find things worth
fetching". Different inputs, and a crawler that only accepts the first makes
the user do the discovery by hand.

WHAT THE LLM IS AND IS NOT FOR.
It ranks and filters search results: is this an actual ARTICLE, or a category
page, a tag listing, a product page, a login-walled aggregator? That is
genuine judgement, of a kind heuristics do badly, and a wrong answer costs
one wasted fetch rather than corrupted data. That is the right risk profile
for a model.

TWO HARD RULES:

  1. The LLM NEVER bypasses a gate. Its output is a suggestion list, and
     every URL still goes through normalisation, robots.txt, rate limiting,
     block detection and the quality gates unchanged. A model saying "this is
     a great article" is not permission to fetch anything.

  2. It degrades, it does not die. No GROQ_API_KEY -> skip ranking and return
     the search results in provider order. No TAVILY_API_KEY -> DuckDuckGo,
     which needs no key. The core crawl needs neither.

The search layer is the same two-provider design as Day 2's web_search tool,
for the same reason: the tool must work on a machine that has never signed up
for anything, which matters for CI and for whoever reviews this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import Config

_MAX_SEARCH_RESULTS = 12
_MAX_SNIPPET_CHARS = 300


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str
    snippet: str
    score: float | None = None
    """LLM relevance score 0-1, or None when ranking was skipped."""
    reason: str | None = None
    """Why the model kept or dropped it. Shown in the UI so the user can
    disagree with the model rather than trust it blindly."""


class SearchUnavailable(RuntimeError):
    """Every configured search provider failed.

    Distinct from "the search ran and found nothing". The first time discover
    was run without a key, DuckDuckGo's backend timed out and the user saw a
    bare "No results." -- which reads as "your topic has no articles" when the
    truth was "search never happened". Different problems deserve different
    messages.
    """


def _search(query: str, config: Config) -> list[Candidate]:
    """Web search: Tavily when a key is present, DuckDuckGo otherwise.

    Raises SearchUnavailable when every provider errored, so the caller can
    distinguish that from an empty result set.
    """
    results: list[Candidate] = []
    failures: list[str] = []

    if config.tavily_api_key:
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=config.tavily_api_key)
            response = client.search(query=query, max_results=_MAX_SEARCH_RESULTS)
            for item in response.get("results", []):
                url = (item.get("url") or "").strip()
                if url:
                    results.append(
                        Candidate(
                            url=url,
                            title=(item.get("title") or "").strip() or "(untitled)",
                            snippet=(item.get("content") or "")[:_MAX_SNIPPET_CHARS],
                        )
                    )
            if results:
                return results
            failures.append("Tavily returned no results")
        except Exception as exc:  # noqa: BLE001 - any failure -> fall back
            failures.append(f"Tavily failed: {exc}")
            print(f"  Tavily search failed ({exc}); falling back to DuckDuckGo.")

    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=_MAX_SEARCH_RESULTS):
                url = (item.get("href") or "").strip()
                if url:
                    results.append(
                        Candidate(
                            url=url,
                            title=(item.get("title") or "").strip() or "(untitled)",
                            snippet=(item.get("body") or "")[:_MAX_SNIPPET_CHARS],
                        )
                    )
        if not results:
            failures.append("DuckDuckGo returned no results")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"DuckDuckGo failed: {exc}")

    if not results and failures:
        # Every provider errored. Raising rather than returning [] so the
        # caller can say "search is unavailable" instead of the misleading
        # "no results found".
        raise SearchUnavailable("; ".join(failures))

    return results


_RANKING_PROMPT = """You are helping a web crawler decide which search results are worth fetching.

The crawler wants individual ARTICLES or BLOG POSTS about: {topic}

For each numbered result, decide whether it is a single readable article.

REJECT (score below 0.3):
- category, tag, archive or index pages that only list other posts
- site homepages
- product, pricing or marketing pages
- forums, Q&A threads, social media posts
- anything that obviously requires a login or subscription
- video or podcast pages with no article text

ACCEPT (score above 0.6): a single article or blog post on the topic.

Reply with ONLY a JSON array, no other text:
[{{"index": 1, "score": 0.9, "reason": "in-depth blog post on the topic"}}]

Results:
{results}
"""


def _rank(candidates: list[Candidate], topic: str, config: Config) -> list[Candidate]:
    """Ask the LLM to score each candidate. Returns them sorted, best first.

    On ANY failure the input list is returned unchanged: ranking is an
    enhancement, and losing it must not lose the search results too.
    """
    if not candidates or not config.groq_api_key:
        return candidates

    listing = "\n".join(
        f"{index + 1}. {candidate.title}\n   {candidate.url}\n   {candidate.snippet}"
        for index, candidate in enumerate(candidates)
    )

    try:
        from groq import Groq

        client = Groq(api_key=config.groq_api_key)
        response = client.chat.completions.create(
            model=config.discovery_model,
            messages=[
                {
                    "role": "user",
                    "content": _RANKING_PROMPT.format(topic=topic, results=listing),
                }
            ],
            # Low temperature: this is a classification task, not a creative
            # one, and run-to-run variation on the same inputs would make the
            # discovery step irreproducible.
            temperature=0.1,
            max_tokens=1200,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        print(f"  LLM ranking unavailable ({exc}); returning unranked results.")
        return candidates

    # Models wrap JSON in markdown fences despite being told not to. Strip
    # them rather than failing the whole step over formatting.
    if raw.startswith("```"):
        raw = raw.split("```")[1] if "```" in raw[3:] else raw[3:]
        raw = raw.removeprefix("json").strip()

    try:
        scores = json.loads(raw)
    except (ValueError, TypeError):
        print("  LLM returned unparseable JSON; returning unranked results.")
        return candidates

    by_index: dict[int, dict] = {}
    if isinstance(scores, list):
        for entry in scores:
            if isinstance(entry, dict) and isinstance(entry.get("index"), int):
                by_index[entry["index"]] = entry

    ranked: list[Candidate] = []
    for index, candidate in enumerate(candidates, start=1):
        entry = by_index.get(index, {})
        raw_score = entry.get("score")
        score = float(raw_score) if isinstance(raw_score, (int, float)) else None
        ranked.append(
            Candidate(
                url=candidate.url,
                title=candidate.title,
                snippet=candidate.snippet,
                score=score,
                reason=(entry.get("reason") or None),
            )
        )

    # Unscored entries sort last but are NOT dropped: a model that returned a
    # short list should not silently delete results the user could still use.
    ranked.sort(key=lambda c: (c.score if c.score is not None else -1.0), reverse=True)
    return ranked


def discover(topic: str, config: Config, min_score: float = 0.5) -> list[Candidate]:
    """Search for `topic` and return candidates, best first.

    `min_score` filters only when ranking actually ran; unranked candidates
    are always returned so the feature degrades to plain search.
    """
    candidates = _search(topic, config)
    if not candidates:
        return []

    ranked = _rank(candidates, topic, config)

    if any(candidate.score is not None for candidate in ranked):
        return [c for c in ranked if c.score is None or c.score >= min_score]
    return ranked
