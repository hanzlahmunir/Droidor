"""Token pricing and per-call cost computation.

WHY THIS FILE EXISTS: the Groq API returns token COUNTS but never a dollar
amount, so cost must be computed client-side from a price table we maintain.

IMPORTANT HONESTY NOTE: we develop against Groq's free tier, where actual
billed spend is $0. Every figure produced here is therefore a *modelled* cost
-- "what this session would cost at published paid rates" -- not an invoice.
The before/after numbers in the README are modelled costs, which is exactly
what the exercise asks for, but they should never be presented as billing data.

Rates are USD per 1,000,000 tokens, from https://groq.com/pricing
as published on 2026-07-29. Prices drift; this table is the single place to
update when they do.
"""

from dataclasses import dataclass

# model id -> (input $/Mtok, output $/Mtok)
_RATES: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "moonshotai/kimi-k2-instruct-0905": (1.00, 3.00),
}

# Used when an unknown model id shows up, so cost tracking degrades to an
# over-estimate instead of silently reporting $0 and hiding real spend.
_FALLBACK_RATE: tuple[float, float] = (1.00, 3.00)

_TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class TurnCost:
    """Cost breakdown for a single API call."""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_cost_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd


def rates_for(model: str) -> tuple[float, float]:
    """Return (input, output) $/Mtok for a model, falling back to a high estimate."""
    return _RATES.get(model, _FALLBACK_RATE)


def is_known_model(model: str) -> bool:
    """False means cost is an over-estimate from the fallback rate."""
    return model in _RATES


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> TurnCost:
    """Convert raw token counts into a costed record.

    Input and output are priced separately because output is consistently the
    more expensive side (here ~1.3x on 70b, ~1.6x on 8b). Collapsing them into
    one blended rate would make the optimisation work impossible to attribute.
    """
    in_rate, out_rate = rates_for(model)
    return TurnCost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_tokens / _TOKENS_PER_MILLION * in_rate,
        output_cost_usd=output_tokens / _TOKENS_PER_MILLION * out_rate,
    )
