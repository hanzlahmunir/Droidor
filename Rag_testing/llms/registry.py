"""Key-driven LLM registry.

The set of providers offered to the UI is derived entirely from which API keys
are present in the environment (`.env`). This is the mechanism the plan relies
on: the user sees only what they can actually run today, and additional
providers light up automatically when the lead adds keys — no code change.

Providers:
  anthropic / openai / google  -> LangChain's unified ``init_chat_model``
  xai (Grok)                   -> ``langchain_xai.ChatXAI``
  groq                         -> ``langchain_groq.ChatGroq``

The numeric "effort" knob is translated to a provider-appropriate native
reasoning setting where supported (see ``config.effort_to_settings``).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from config import MODELS, PROVIDER_LABELS

load_dotenv()

# Which env var gates each provider, and the model_provider string for
# init_chat_model (None => the provider has its own dedicated adapter below).
_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
}

_INIT_CHAT_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google_genai",
    "groq": "groq",
}


def _has_key(env_var: str) -> bool:
    """True only for a value that plausibly is a real key.

    Guards against a blank or comment-only value (e.g. dotenv parsing a
    trailing inline comment as the value), which would otherwise make a
    provider appear configured when it isn't.
    """
    val = (os.getenv(env_var) or "").strip()
    return bool(val) and not val.startswith("#")


def available_providers() -> list[str]:
    """Return provider ids that have an API key set, in catalog order."""
    return [p for p in MODELS if _has_key(_PROVIDER_ENV[p])]


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def models_for(provider: str) -> list[str]:
    return MODELS.get(provider, [])


def _reasoning_kwargs(provider: str, model: str, reasoning_effort: str) -> dict:
    """Provider-specific way to pass the native reasoning-effort setting.

    Only some models support it; unsupported combos get no reasoning kwarg so
    the call still succeeds.
    """
    if provider == "xai":
        # Grok reasoning models (e.g. grok-3-mini) accept low|high via extra_body.
        # Non-reasoning models (grok-4) ignore/reject it, so only send for -mini.
        if "mini" in model:
            level = "high" if reasoning_effort == "high" else "low"
            return {"extra_body": {"reasoning_effort": level}}
        return {}
    if provider == "openai":
        # o-series reasoning models accept reasoning_effort low|medium|high.
        if model.startswith("o"):
            return {"reasoning_effort": reasoning_effort}
        return {}
    # anthropic / google / groq: reasoning is model-default here; no explicit knob.
    return {}


def get_llm(provider: str, model: str, reasoning_effort: str = "medium", temperature: float = 0.0):
    """Build a LangChain chat model for ``provider``/``model``.

    ``reasoning_effort`` (low|medium|high) is passed to the model's native
    reasoning setting where supported. Raises ``RuntimeError`` if the provider
    has no API key.
    """
    if provider not in _PROVIDER_ENV:
        raise ValueError(f"Unknown provider: {provider!r}")
    if not _has_key(_PROVIDER_ENV[provider]):
        raise RuntimeError(
            f"No API key for provider {provider!r} "
            f"(set {_PROVIDER_ENV[provider]} in .env)."
        )

    reasoning = _reasoning_kwargs(provider, model, reasoning_effort)

    if provider == "xai":
        from langchain_xai import ChatXAI

        return ChatXAI(model=model, temperature=temperature, **reasoning)

    from langchain.chat_models import init_chat_model

    return init_chat_model(
        model,
        model_provider=_INIT_CHAT_PROVIDER[provider],
        temperature=temperature,
        **reasoning,
    )
