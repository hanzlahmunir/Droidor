"""Tool registry: JSON schemas for the model, plus safe dispatch.

ERROR HANDLING LAYER 1 of 3 (see cli.py for layers 2 and 3).

Every tool call is wrapped so that NO exception escapes into the chat loop. A
failed tool returns an error *string*, which is sent back to the model as a
normal tool result. The model then reads "Error: timed out" and adapts -- it
might retry, try a different URL, or tell the user. That is the behaviour the
brief asks for: tool errors must not crash the chat.

The bare `except Exception` here is deliberate and is the one place in this
codebase where it is correct: a third-party library raising something we did
not anticipate must still become a chat message, not a traceback.
"""

from typing import Any, Callable

from app.tools.calculator import CalculatorError, calculate
from app.tools.fetch_url import FetchError, fetch_url
from app.tools.web_search import SearchError, search

# Tool schemas in OpenAI/Groq function-calling format.
#
# COST NOTE: these descriptions are re-sent to the API on EVERY turn, so their
# length is a permanent per-turn tax. They are written to be just long enough
# for correct tool selection and no longer.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluate an arithmetic expression. Supports + - * / // % ** "
                "and parentheses. Use for any calculation rather than doing "
                "mental arithmetic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression, e.g. '(2+3)*4'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web and return titles, URLs and snippets. Use for "
                "current events or facts you are unsure about. Follow up with "
                "fetch_url to read a specific result in full."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch a single http/https URL and return its readable text. "
                "Use after web_search to read a promising result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full http:// or https:// URL",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


def _run_calculator(args: dict[str, Any], _cfg: Any) -> str:
    expression = args.get("expression")
    if not isinstance(expression, str):
        raise CalculatorError("Missing required argument: expression")
    return f"{expression} = {calculate(expression)}"


def _run_web_search(args: dict[str, Any], cfg: Any) -> str:
    query = args.get("query")
    if not isinstance(query, str):
        raise SearchError("Missing required argument: query")

    tavily_key = getattr(cfg, "tavily_api_key", None)
    results = search(query, tavily_api_key=tavily_key)

    return "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\n{r.snippet}"
        for i, r in enumerate(results, start=1)
    )


def _run_fetch_url(args: dict[str, Any], _cfg: Any) -> str:
    url = args.get("url")
    if not isinstance(url, str):
        raise FetchError("Missing required argument: url")
    return fetch_url(url)


_DISPATCH: dict[str, Callable[[dict[str, Any], Any], str]] = {
    "calculator": _run_calculator,
    "web_search": _run_web_search,
    "fetch_url": _run_fetch_url,
}


def run_tool(name: str, args: dict[str, Any], cfg: Any) -> str:
    """Execute a tool by name, converting every failure into a string.

    This function never raises. The return value always goes back to the model
    as a tool result, error or not.
    """
    handler = _DISPATCH.get(name)
    if handler is None:
        # The model hallucinated a tool name. Telling it so is more useful
        # than failing, because it can then pick a real one.
        return (
            f"Error: unknown tool {name!r}. "
            f"Available tools: {', '.join(sorted(_DISPATCH))}."
        )

    try:
        return handler(args, cfg)
    except (CalculatorError, FetchError, SearchError) as exc:
        # Expected, well-typed failures: bad expression, blocked URL, dead
        # search provider. The message is written for the model to act on.
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 - see module docstring
        # Unexpected failure inside a dependency. Still must not crash the chat.
        return f"Error: {type(exc).__name__} while running {name}: {exc}"
