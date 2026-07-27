"""Lightweight metrics: wall-clock latency, token usage, and cost estimate.

Token/cost capture is best-effort and provider-agnostic: we attach a LangChain
usage-metadata callback during the run and read aggregate token counts from it.
Cost is estimated from a small per-model price table (USD per 1M tokens); models
not in the table report tokens but no cost.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from langchain_core.callbacks import UsageMetadataCallbackHandler

# Rough public prices, USD per 1M tokens (input, output). Extend as needed;
# unknown models simply won't get a cost estimate.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "o3-mini": (1.1, 4.4),
    "gemini-2.0-flash": (0.1, 0.4),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.3),
    "grok-4": (5.0, 15.0),
    "grok-3-mini": (0.3, 0.5),
    "grok-3-fast": (5.0, 25.0),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


@contextmanager
def timer():
    """Yield a callable returning elapsed seconds so far."""
    start = time.perf_counter()
    elapsed = {"value": 0.0}

    def read() -> float:
        return time.perf_counter() - start

    try:
        yield read
    finally:
        elapsed["value"] = time.perf_counter() - start


def new_usage_callback() -> UsageMetadataCallbackHandler:
    """A callback that aggregates token usage across all LLM calls in a run."""
    return UsageMetadataCallbackHandler()


def summarize_usage(callback: UsageMetadataCallbackHandler, model: str):
    """Return (total_tokens, cost_usd_or_None) from an aggregated usage callback."""
    usage = getattr(callback, "usage_metadata", None) or {}
    in_tok = out_tok = 0
    # usage_metadata is keyed by model name; sum across whatever was used.
    for data in usage.values():
        in_tok += data.get("input_tokens", 0) or 0
        out_tok += data.get("output_tokens", 0) or 0
    total = in_tok + out_tok
    if total == 0:
        return None, None

    price = _PRICES.get(model)
    if not price:
        return total, None
    cost = (in_tok / 1_000_000) * price[0] + (out_tok / 1_000_000) * price[1]
    return total, round(cost, 6)
