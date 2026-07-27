"""Central configuration for the RAG testbed.

Defines the :class:`RagConfig` object that fully describes a single pipeline
run, the option tables the UI builds its dropdowns from, and the mapping from
the numeric "effort" knob to concrete pipeline behavior.

Keeping every dimension (framework, store, LLM, effort) as data here is what
makes this a *testbed*: adding an option is a data/adapter change, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- Paths ---
ROOT = Path(__file__).resolve().parent
CHROMA_DIR = ROOT / "chroma_db"
CHROMA_COLLECTION = "amazon_toys_and_games"
DATA_DIR = ROOT / "data"

# --- Dataset ---
# Amazon Reviews 2023 ships a loader *script* that newer `datasets` refuses to
# run, and only 9 categories are materialized as standalone parquet folders in
# the repo (Video Games is NOT among them). We load the parquet shards directly.
# Toys_and_Games is the closest available fit (games/hobby products, rich meta).
HF_DATASET = "McAuley-Lab/Amazon-Reviews-2023"
HF_META_CONFIG = "raw_meta_Toys_and_Games"
# Direct parquet URLs (shard 0 is enough for a large sample; add more for scale).
HF_PARQUET_SHARDS = [
    "hf://datasets/McAuley-Lab/Amazon-Reviews-2023/"
    f"{HF_META_CONFIG}/full-0000{i}-of-00005.parquet"
    for i in range(5)
]

# --- Options the UI offers ---
FRAMEWORKS = ["langchain", "langgraph"]  # a 3rd (LlamaIndex/Haystack/etc.) is a future add
STORES = ["chroma", "neo4j"]

# Model catalog per provider (latest-first). The UI only shows providers whose
# API key is present (see llms/registry.available_providers), so this can list
# every provider safely.
MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "xai": ["grok-4", "grok-3-mini", "grok-3-fast"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
}

# Human-friendly labels for the provider dropdown.
PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "google": "Google (Gemini)",
    "xai": "xAI (Grok)",
    "groq": "Groq (fast inference)",
}

# "effort" = the max number of reform rounds: how many times the LangGraph
# pipeline may retrieve -> grade -> rewrite-and-retry before answering. You type
# it directly (e.g. 10, 20). Soft-capped so a typo can't burn the whole quota.
EFFORT_MIN, EFFORT_MAX, EFFORT_DEFAULT = 1, 25, 3

# k (chunks retrieved) bounds + default for the numeric input.
K_MIN, K_MAX, K_DEFAULT = 1, 30, 6

REASONING_LEVELS = ["low", "medium", "high"]
DEFAULT_REASONING = "medium"


@dataclass
class RagConfig:
    """A complete description of one pipeline run — one 'config window'.

    Every retrieval/reasoning knob is independent so any window is fully
    configurable regardless of framework. ``effort`` = max reform rounds (used
    only by LangGraph); ``grade_docs`` also only applies to LangGraph's loop.
    """

    llm_provider: str
    llm_model: str
    effort: int = EFFORT_DEFAULT           # max reform rounds (LangGraph only)
    framework: str = "langchain"
    store: str = "chroma"
    # Independent knobs (apply to both frameworks unless noted):
    k: int = K_DEFAULT                      # chunks retrieved
    rewrite_query: bool = True              # LLM query-rewrite prepass
    grade_docs: bool = True                 # doc grading + retry (LangGraph only)
    reasoning_effort: str = DEFAULT_REASONING  # native reasoning: low|med|high
    label: str = ""                         # optional display name

    def __post_init__(self) -> None:
        self.effort = max(EFFORT_MIN, min(EFFORT_MAX, int(self.effort)))
        self.k = max(K_MIN, min(K_MAX, int(self.k)))
        if self.reasoning_effort not in REASONING_LEVELS:
            self.reasoning_effort = DEFAULT_REASONING


@dataclass
class EffortSettings:
    """Concrete pipeline behavior for a run (resolved from a RagConfig)."""

    k: int                       # number of chunks to retrieve
    rewrite_query: bool          # do an LLM query-rewrite prepass
    grade_docs: bool             # grade retrieved docs and retry retrieval (LangGraph)
    reasoning_effort: str        # native model reasoning effort: low|medium|high
    max_retrieval_rounds: int    # how many reform-and-retry rounds are allowed


def settings_from_config(cfg: "RagConfig") -> EffortSettings:
    """Resolve the independent knobs on a RagConfig into EffortSettings."""
    return EffortSettings(
        k=cfg.k,
        rewrite_query=cfg.rewrite_query,
        grade_docs=cfg.grade_docs,
        reasoning_effort=cfg.reasoning_effort,
        max_retrieval_rounds=max(EFFORT_MIN, min(EFFORT_MAX, int(cfg.effort))),
    )


def effort_to_settings(effort: int) -> EffortSettings:
    """Back-compat: build settings from just a reform-round budget + defaults.

    Retained for tests/callers that pass only the round count; the UI now uses
    settings_from_config to honor every per-window knob.
    """
    rounds = max(EFFORT_MIN, min(EFFORT_MAX, int(effort)))
    return EffortSettings(
        k=K_DEFAULT,
        rewrite_query=True,
        grade_docs=True,
        reasoning_effort=DEFAULT_REASONING,
        max_retrieval_rounds=rounds,
    )
