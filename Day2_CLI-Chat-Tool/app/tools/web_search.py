"""Web search with a primary provider and a keyless fallback.

Tavily is the primary: it is built for LLM agents, returns clean snippets, and
has a genuinely monthly free tier (1000 credits/month). DuckDuckGo via the
`ddgs` package is the fallback: no API key at all, so the tool still works on a
machine that has never signed up for anything -- which matters for CI and for
whoever reviews this.

Both are hidden behind one `search()` function returning the same shape, so
swapping providers is a change in this file only.
"""

from dataclasses import dataclass

# Number of results requested. Each result costs tokens on every subsequent
# turn once it is in history, so this is deliberately small.
_MAX_RESULTS = 5

# Per-result snippet cap, for the same reason.
_MAX_SNIPPET_CHARS = 400


class SearchError(RuntimeError):
    """Raised when every configured search provider fails."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def _truncate(text: str, limit: int = _MAX_SNIPPET_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _search_tavily(query: str, api_key: str) -> list[SearchResult]:
    """Search via Tavily. Raises on any failure so the caller can fall back."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)
    response = client.search(query=query, max_results=_MAX_RESULTS)

    return [
        SearchResult(
            title=item.get("title", "").strip() or "(untitled)",
            url=item.get("url", "").strip(),
            snippet=_truncate(item.get("content", "")),
        )
        for item in response.get("results", [])
    ]


def _search_duckduckgo(query: str) -> list[SearchResult]:
    """Search via DuckDuckGo. No API key, but aggressively rate-limited."""
    from ddgs import DDGS

    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=_MAX_RESULTS))

    return [
        SearchResult(
            title=(item.get("title") or "").strip() or "(untitled)",
            url=(item.get("href") or "").strip(),
            snippet=_truncate(item.get("body") or ""),
        )
        for item in raw
    ]


def search(query: str, tavily_api_key: str | None = None) -> list[SearchResult]:
    """Search the web, preferring Tavily and falling back to DuckDuckGo.

    Raises SearchError only if every available provider fails, so a transient
    Tavily outage degrades to slower-but-working search rather than a dead tool.
    """
    if not query or not query.strip():
        raise SearchError("Search query must be a non-empty string.")

    query = query.strip()
    failures: list[str] = []

    if tavily_api_key:
        try:
            results = _search_tavily(query, tavily_api_key)
            if results:
                return results
            failures.append("Tavily returned no results")
        except Exception as exc:  # noqa: BLE001 - any provider failure -> fall back
            failures.append(f"Tavily failed: {exc}")

    try:
        results = _search_duckduckgo(query)
        if results:
            return results
        failures.append("DuckDuckGo returned no results")
    except Exception as exc:  # noqa: BLE001 - last resort; report and give up
        failures.append(f"DuckDuckGo failed: {exc}")

    raise SearchError("; ".join(failures))
