"""Run every configuration N times and report means with spread.

WHY REPEATS ARE NOT OPTIONAL: a single run per config is not evidence. The
model decides how many times to search, and that choice varies between runs
on identical input. Measured spread on this transcript is up to ~23% of the
mean, which is larger than several of the effects being measured -- so a
single-run comparison can rank a worse config above a better one purely by
luck. (An early single-run measurement did exactly that.)

Reports mean, stdev and range per config, and recall alongside cost, because
a cheaper config that forgets the user's name is not an improvement.

Usage:
    python compare.py --repeats 3
"""

import argparse
import json
import statistics
from pathlib import Path

from app.cli import _force_utf8_stdout
from app.optimize import OptimizationFlags
from benchmark import run_benchmark

# (label, description, flags)
CONFIGS: list[tuple[str, str, OptimizationFlags]] = [
    ("baseline", "full history, no optimisations", OptimizationFlags()),
    (
        "A",
        "per-tool result caps",
        OptimizationFlags(truncate_tool_results=True),
    ),
    (
        "C",
        "cheap-model routing",
        OptimizationFlags(route_models=True),
    ),
    # Config B (summarisation alone) is measured in the A+B row rather than on
    # its own: single-run measurement already showed it is a net LOSS on a
    # 10-turn session (3 extra API calls / ~4,300 tokens of overhead against a
    # ~10% per-turn saving). It is kept in the codebase and in the A+B+C row
    # because the overhead is fixed while the saving grows with session length,
    # so it turns positive on longer sessions -- see docs/COST.md.
    (
        "A+B",
        "caps + summary (overhead vs saving)",
        OptimizationFlags(truncate_tool_results=True, summarize_history=True),
    ),
    (
        "A+C",
        "caps + routing",
        OptimizationFlags(truncate_tool_results=True, route_models=True),
    ),
    (
        "A+B+C",
        "all three",
        OptimizationFlags(
            truncate_tool_results=True, summarize_history=True, route_models=True
        ),
    ),
]


def main() -> int:
    _force_utf8_stdout()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--only", default="", help="comma-separated config labels to run"
    )
    args = parser.parse_args()

    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    configs = [c for c in CONFIGS if not wanted or c[0] in wanted]

    results: dict[str, dict] = {}

    for label, description, flags in configs:
        costs: list[float] = []
        calls: list[int] = []
        recalls: list[int] = []

        print(f"\n{'=' * 60}\n{label}: {description}\n{'=' * 60}", flush=True)
        run = 0
        attempts = 0
        # A full sweep is ~18 runs and several minutes of network calls. A
        # single transient connection error part-way through must not discard
        # every completed run, so failures are retried instead of aborting.
        # (An earlier version inherited benchmark.py's fail-fast and lost 17
        # good runs to one blip.)
        while run < args.repeats and attempts < args.repeats * 3:
            attempts += 1
            try:
                summary = run_benchmark(label, description, quiet=True, flags=flags)
            except SystemExit:
                print(f"  run {run}: FAILED (transient) - retrying", flush=True)
                continue

            costs.append(summary["cost_per_turn_usd"])
            calls.append(summary["api_calls"])
            recalls.append(summary["recall_passed"])
            print(
                f"  run {run}: ${summary['cost_per_turn_usd']:.6f}  "
                f"calls={summary['api_calls']:>3}  "
                f"recall={summary['recall_passed']}/{summary['recall_total']}",
                flush=True,
            )
            run += 1

        if not costs:
            print(f"  {label}: no successful runs, skipping", flush=True)
            continue

        results[label] = {
            "description": description,
            "repeats": args.repeats,
            "mean_cost_per_turn": statistics.mean(costs),
            "stdev": statistics.stdev(costs) if len(costs) > 1 else 0.0,
            "min": min(costs),
            "max": max(costs),
            "mean_api_calls": statistics.mean(calls),
            "recall_all_passed": all(r == 3 for r in recalls),
            "recall_runs": recalls,
        }

    baseline_mean = results.get("baseline", {}).get("mean_cost_per_turn")

    print(f"\n{'=' * 74}")
    print("SUMMARY (mean of", args.repeats, "runs each)")
    print("=" * 74)
    print(f"{'config':<10} {'mean/turn':>12} {'stdev':>10} {'vs base':>9} "
          f"{'calls':>6} {'recall':>8}")
    print("-" * 74)
    for label, r in results.items():
        delta = (
            f"{(r['mean_cost_per_turn'] / baseline_mean - 1) * 100:+.0f}%"
            if baseline_mean
            else "n/a"
        )
        recall = "3/3 all" if r["recall_all_passed"] else f"FAIL {r['recall_runs']}"
        print(
            f"{label:<10} ${r['mean_cost_per_turn']:>11.6f} "
            f"${r['stdev']:>9.6f} {delta:>9} "
            f"{r['mean_api_calls']:>6.1f} {recall:>8}"
        )

    Path("docs").mkdir(exist_ok=True)
    with open("docs/comparison.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print("\nwritten to docs/comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
