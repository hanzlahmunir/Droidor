"""History management and the optimisation helpers.

The rollback test guards the subtlest bug in the project: a turn that dies
between appending an assistant tool_call and appending its tool result leaves
history permanently malformed, and every LATER request 400s. The chat appears
to work, then fails forever.
"""

import json

from app.conversation import Conversation
from app.optimize import (
    OptimizationFlags,
    estimate_tokens,
    should_use_cheap_model,
    truncate_tool_result,
)


def test_system_prompt_is_separate_from_turns():
    """Trimming logic must not be able to drop the system prompt."""
    conv = Conversation("SYSTEM")
    conv.append({"role": "user", "content": "hi"})

    assert conv.messages[0]["role"] == "user"  # not in the turn list
    assert conv.to_api_messages()[0] == {"role": "system", "content": "SYSTEM"}


def test_rollback_removes_orphaned_tool_call():
    """The bug this exists to prevent."""
    conv = Conversation("sys")
    conv.append({"role": "user", "content": "turn 1"})
    conv.append({"role": "assistant", "content": "reply 1"})

    marker = conv.snapshot()

    # A turn that dies after the tool_call but before the tool result.
    conv.append({"role": "user", "content": "turn 2"})
    conv.append(
        {"role": "assistant", "content": None, "tool_calls": [{"id": "orphan"}]}
    )

    conv.rollback(marker)

    assert len(conv.messages) == 2
    assert not any("tool_calls" in m for m in conv.messages)


def test_transcript_keeps_the_failed_turn(tmp_path):
    """Rollback trims live history only; the transcript is evidence."""
    path = tmp_path / "t.jsonl"
    conv = Conversation("sys", transcript_path=str(path))
    conv.append({"role": "user", "content": "kept"})
    marker = conv.snapshot()
    conv.append({"role": "user", "content": "rolled back"})
    conv.rollback(marker)

    assert len(conv.messages) == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # both were written


def test_record_event_reaches_the_transcript(tmp_path):
    """Summarisation rewrites history directly, bypassing append()."""
    path = tmp_path / "t.jsonl"
    conv = Conversation("sys", transcript_path=str(path))
    conv.record_event({"event": "history_summarized", "summary": "facts"})

    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["event"] == "history_summarized"


# --- Optimisation A --------------------------------------------------------


def test_truncation_disabled_is_a_true_no_op():
    """Baseline must be untouched, not merely configured with a big limit."""
    big = "x" * 50_000
    assert truncate_tool_result(big, enabled=False, tool_name="fetch_url") == big


def test_per_tool_caps_differ():
    """A single global cap starved fetch_url and cost MORE than baseline."""
    big = "x" * 50_000
    search = truncate_tool_result(big, True, "web_search")
    fetch = truncate_tool_result(big, True, "fetch_url")
    assert len(fetch) > len(search)


def test_truncation_marks_that_content_was_cut():
    """Without the marker the model assumes the source ended and re-fetches."""
    result = truncate_tool_result("x" * 50_000, True, "web_search")
    assert "truncated" in result


def test_short_results_pass_through_untouched():
    assert truncate_tool_result("2+2 = 4", True, "calculator") == "2+2 = 4"


# --- Optimisation C --------------------------------------------------------


def test_routing_disabled_always_uses_the_capable_model():
    assert should_use_cheap_model("hi", enabled=False) is False


def test_simple_turns_route_to_the_cheap_model():
    for message in ("What is my name?", "Thanks!", "yes"):
        assert should_use_cheap_model(message, enabled=True) is True


def test_tool_and_reasoning_turns_stay_on_the_capable_model():
    for message in (
        "What is 1847 * 293? Use the calculator.",
        "Search the web for X",
        "Explain why tuples are immutable",
        "Fetch https://example.com",
    ):
        assert should_use_cheap_model(message, enabled=True) is False


def test_long_messages_stay_on_the_capable_model():
    """Length is a cheap proxy for complexity; the router must stay free."""
    assert should_use_cheap_model("word " * 100, enabled=True) is False


# --- misc ------------------------------------------------------------------


def test_token_estimate_scales_with_content():
    small = estimate_tokens([{"role": "user", "content": "hi"}])
    large = estimate_tokens([{"role": "user", "content": "x" * 4000}])
    assert large > small
    assert 900 < large < 1100  # ~4 chars/token


def test_flag_labels_are_distinguishable():
    assert OptimizationFlags().label == "baseline"
    assert OptimizationFlags(truncate_tool_results=True).label == "trunc"
    assert OptimizationFlags(True, True, True).label == "trunc+summary+routing"
