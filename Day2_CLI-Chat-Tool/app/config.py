"""Central configuration, read from the environment.

Secrets have NO default: a missing GROQ_API_KEY raises KeyError at import time
rather than failing later with a confusing 401 mid-conversation. Non-secret
settings have defaults so the tool runs out of the box.
"""

import os

from dotenv import load_dotenv

# Load .env into os.environ if present. Real deployments set env vars directly,
# so a missing .env file is not an error.
load_dotenv()


class Config:
    """Runtime settings. Instantiated once in cli.py and passed down."""

    def __init__(self) -> None:
        # No default -> fail fast and loudly if the key is missing.
        self.groq_api_key: str = os.environ["GROQ_API_KEY"]

        # Optional: empty string means "no Tavily", and web_search falls back
        # to DuckDuckGo. We normalise to None so callers do a simple `if`.
        self.tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY") or None

        # Defaults chosen by measurement, not preference: on a tool-heavy
        # prompt llama-3.3-70b-versatile answered 0/4 correctly and failed to
        # emit valid tool-call JSON on 1 call in 4, while gpt-oss-120b was 4/4
        # with no failures -- and is ~4x cheaper on input. See docs/COST.md.
        self.chat_model: str = os.environ.get("CHAT_MODEL", "openai/gpt-oss-120b")
        self.cheap_model: str = os.environ.get("CHEAP_MODEL", "openai/gpt-oss-20b")

        self.cost_log_path: str = os.environ.get("COST_LOG_PATH", "logs/cost_log.jsonl")

        # Hard cap on tokens generated per reply. This is a safety valve against
        # a runaway response costing 100x a normal turn, not a target length.
        self.max_tokens: int = int(os.environ.get("MAX_TOKENS", "1024"))
