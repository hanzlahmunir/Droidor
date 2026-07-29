"""Cost arithmetic and logging.

The entire deliverable is a cost number, so an error here silently corrupts
the before/after comparison rather than failing loudly.
"""

import json

import pytest

from app.costlog import CostLogger
from app.pricing import compute_cost, is_known_model, rates_for


def test_known_model_rates():
    """Verified against groq.com/pricing on 2026-07-29."""
    assert rates_for("openai/gpt-oss-120b") == (0.15, 0.60)
    assert rates_for("openai/gpt-oss-20b") == (0.075, 0.30)


def test_cost_is_computed_per_million_tokens():
    cost = compute_cost("openai/gpt-oss-120b", 1_000_000, 1_000_000)
    assert cost.input_cost_usd == 0.15
    assert cost.output_cost_usd == 0.60
    assert cost.total_cost_usd == 0.75


def test_input_and_output_are_priced_separately():
    """Output costs 4x input here; a blended rate would hide that."""
    cost = compute_cost("openai/gpt-oss-120b", 1000, 1000)
    assert cost.output_cost_usd == cost.input_cost_usd * 4


def test_unknown_model_uses_fallback_and_is_flagged():
    """An unknown model must over-estimate, never silently report $0."""
    assert not is_known_model("some-new-model")
    cost = compute_cost("some-new-model", 1_000_000, 0)
    assert cost.input_cost_usd > 0


def test_zero_tokens_is_zero_cost():
    assert compute_cost("openai/gpt-oss-120b", 0, 0).total_cost_usd == 0.0


def test_cost_log_writes_one_row_per_call(tmp_path):
    path = tmp_path / "cost.jsonl"
    logger = CostLogger(str(path), config_label="test")

    logger.record(compute_cost("openai/gpt-oss-120b", 100, 50), 0, 0)
    logger.record(compute_cost("openai/gpt-oss-120b", 200, 60), 0, 1)
    logger.mark_turn_complete()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    # Both calls belong to turn 0 -- this is what makes a multi-call turn
    # attributable to the turn that caused it.
    assert rows[0]["turn_index"] == rows[1]["turn_index"] == 0
    assert rows[0]["call_index"] == 0
    assert rows[1]["call_index"] == 1


def test_cost_per_turn_divides_by_turns_not_calls(tmp_path):
    """The headline metric. A turn using 3 tools is still ONE turn."""
    logger = CostLogger(str(tmp_path / "c.jsonl"), config_label="test")
    for call in range(3):
        logger.record(compute_cost("openai/gpt-oss-120b", 1_000_000, 0), 0, call)
    logger.mark_turn_complete()

    assert logger.totals.calls == 3
    assert logger.totals.turns == 1
    # 3 * $0.15, NOT divided by the 3 calls. pytest.approx because 0.15*3 is
    # not exactly representable in binary floating point.
    assert logger.totals.cost_per_turn_usd == pytest.approx(0.45)


def test_session_summary_is_appended(tmp_path):
    path = tmp_path / "cost.jsonl"
    logger = CostLogger(str(path), config_label="test")
    logger.record(compute_cost("openai/gpt-oss-120b", 100, 50), 0, 0)
    logger.mark_turn_complete()
    summary = logger.write_session_summary()

    assert summary["type"] == "session_summary"
    assert summary["turns"] == 1
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["type"] == "session_summary"


def test_logging_failure_does_not_raise(tmp_path):
    """A broken cost log must not take down the chat."""
    logger = CostLogger(str(tmp_path / "c.jsonl"), config_label="test")
    logger.path = tmp_path  # a directory: writing to it raises OSError
    logger.record(compute_cost("openai/gpt-oss-120b", 10, 10), 0, 0)  # must not raise
