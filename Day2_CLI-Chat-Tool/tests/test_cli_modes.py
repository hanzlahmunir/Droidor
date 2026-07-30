"""--mode and the per-optimisation flags.

These exist so the before/after comparison this project is *about* can be
reproduced without editing source and rebuilding the image. Adopted from the
co-intern's tool during peer review; ours previously hardcoded the flags in
cli.py, which made the headline result the hardest thing in the repo to check.
"""

import argparse

import pytest

from app.cli import _flags_from_args


def _args(**overrides) -> argparse.Namespace:
    base = {
        "mode": "optimized",
        "no_truncate": False,
        "no_routing": False,
        "summarize": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_simple_mode_is_the_measured_baseline():
    """--mode simple must disable everything, or the 'before' number is wrong."""
    flags = _flags_from_args(_args(mode="simple"))
    assert not flags.truncate_tool_results
    assert not flags.route_models
    assert not flags.summarize_history
    assert flags.label == "baseline"


def test_simple_mode_ignores_the_other_flags():
    """Baseline means baseline; a stray --summarize must not contaminate it."""
    flags = _flags_from_args(_args(mode="simple", summarize=True))
    assert not flags.summarize_history
    assert flags.label == "baseline"


def test_optimized_mode_enables_the_measured_wins():
    flags = _flags_from_args(_args())
    assert flags.truncate_tool_results
    assert flags.route_models
    assert flags.label == "trunc+routing"


def test_summarisation_is_off_unless_asked_for():
    """Measured as a net loss below ~20 turns -- see docs/COST.md."""
    assert not _flags_from_args(_args()).summarize_history
    assert _flags_from_args(_args(summarize=True)).summarize_history


@pytest.mark.parametrize(
    "overrides,expected_label",
    [
        ({"no_routing": True}, "trunc"),
        ({"no_truncate": True}, "routing"),
        ({"no_truncate": True, "no_routing": True}, "baseline"),
    ],
)
def test_single_lever_isolation(overrides, expected_label):
    """Each optimisation can be disabled alone, which is how the per-change
    numbers in docs/COST.md were attributed."""
    assert _flags_from_args(_args(**overrides)).label == expected_label
