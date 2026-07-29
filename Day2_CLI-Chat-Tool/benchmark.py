"""Fixed-transcript benchmark: the measuring instrument for the cost work.

WHY A SCRIPT AND NOT MANUAL CHATTING: "cost went down" means nothing if the
two runs had different conversations. This replays the SAME 10 turns in the
SAME order against every configuration, so a cost difference is attributable
to the configuration and not to having asked shorter questions.

TRANSCRIPT DESIGN. The turns are chosen to exercise the two things the lead
will check, and they are deliberately in tension:

  turns 0-2  plant concrete facts (name, number, preference)
  turns 3-6  unrelated work, including tool calls that bloat history
  turns 7-9  ask the planted facts back  <- the memory test

Cost optimisation wants to throw away old turns; the recall test needs them.
A run that halves cost but fails recall is a downgrade, not an optimisation,
so this harness scores BOTH and prints them together.

Usage:
    python benchmark.py --config baseline --label "full history, 70b"
"""

import argparse
import json
import sys
from dataclasses import dataclass

import groq

from app.api import ChatError, run_turn
from app.cli import _force_utf8_stdout
from app.config import Config
from app.conversation import Conversation
from app.costlog import CostLogger
from app.optimize import OptimizationFlags


@dataclass(frozen=True)
class Turn:
    prompt: str
    # Substrings, ANY of which counts as recalling the fact. None means this
    # turn is not a recall check.
    #
    # Multiple spellings are listed deliberately. An early version checked only
    # "Postgres" and scored a correct answer as a FAILURE because the model
    # replied "PostgreSQL" -- the instrument was wrong, not the model. Matching
    # is case-insensitive for the same reason.
    expect_any: tuple[str, ...] | None = None


# Facts planted early, checked late. Kept concrete and unusual so a generic
# reply cannot pass by luck.
TRANSCRIPT: tuple[Turn, ...] = (
    Turn("Hi! My name is Hanzlah and I'm an intern at Droidor."),
    Turn("My employee ID is 4471 and I work on the backend team."),
    Turn("I prefer Python over JavaScript, and my favourite database is Postgres."),
    Turn("What is 1847 * 293? Use the calculator tool."),
    Turn("Search the web for what the Model Context Protocol is."),
    Turn("What is (18500 / 37) + 962? Use the calculator."),
    Turn("Briefly, what is the difference between a list and a tuple in Python?"),
    # --- recall checks ---------------------------------------------------
    Turn("What is my name?", expect_any=("hanzlah",)),
    Turn("What is my employee ID and which team am I on?", expect_any=("4471",)),
    Turn(
        "Which database did I say was my favourite, and which language do I prefer?",
        # "postgres" is a prefix of "postgresql", so this covers both spellings.
        expect_any=("postgres",),
    ),
)


def run_benchmark(
    config_label: str,
    description: str,
    quiet: bool,
    flags: OptimizationFlags | None = None,
) -> dict:
    flags = flags or OptimizationFlags()
    cfg = Config()
    client = groq.Groq(api_key=cfg.groq_api_key)

    conversation = Conversation(
        "You are a concise, helpful CLI assistant. "
        "Use the calculator tool for arithmetic rather than computing mentally. "
        "Use web_search for current events or facts you are unsure of. "
        "Remember details the user tells you and refer back to them when relevant. "
        "Keep answers brief unless asked to elaborate.",
        transcript_path=f"logs/bench_{config_label}_transcript.jsonl",
    )
    cost_logger = CostLogger(cfg.cost_log_path, config_label=config_label)

    per_turn: list[dict] = []
    recall_passed = 0
    recall_total = 0

    for index, turn in enumerate(TRANSCRIPT):
        marker = conversation.snapshot()
        conversation.append({"role": "user", "content": turn.prompt})

        if not quiet:
            print(f"\n[{index}] you > {turn.prompt}")
            print("    bot > ", end="", flush=True)

        try:
            result = run_turn(
                client=client,
                conversation=conversation,
                cost_logger=cost_logger,
                cfg=cfg,
                turn_index=index,
                on_text=(lambda _c: None) if quiet else None,
                flags=flags,
            )
        except ChatError as exc:
            conversation.rollback(marker)
            print(f"\n    TURN FAILED: {exc}", file=sys.stderr)
            # A failed turn invalidates the comparison, so stop rather than
            # publish a number computed from a partial run.
            raise SystemExit(1) from None

        cost_logger.mark_turn_complete()

        recall_ok: bool | None = None
        if turn.expect_any is not None:
            recall_total += 1
            reply = result.text.lower()
            recall_ok = any(token in reply for token in turn.expect_any)
            recall_passed += int(recall_ok)

        per_turn.append(
            {
                "turn": index,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "api_calls": result.api_calls,
                "recall_ok": recall_ok,
            }
        )

        if not quiet:
            flag = "" if recall_ok is None else ("  RECALL PASS" if recall_ok else "  RECALL FAIL")
            print(
                f"\n    [in={result.input_tokens} out={result.output_tokens} "
                f"${result.cost_usd:.6f}]{flag}"
            )

    summary = cost_logger.write_session_summary()
    summary["description"] = description
    summary["recall_passed"] = recall_passed
    summary["recall_total"] = recall_total
    summary["per_turn"] = per_turn

    results_path = f"logs/bench_{config_label}_result.json"
    with open(results_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


def main() -> int:
    # Same reason as in cli.py: model output containing emoji must not crash
    # a benchmark run on a cp1252 Windows console.
    _force_utf8_stdout()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="", help="config label for the log")
    parser.add_argument("--label", default="", help="human description of this run")
    parser.add_argument("--quiet", action="store_true", help="suppress streamed output")
    # Each optimisation is opted into separately so savings stay attributable.
    parser.add_argument("--truncate", action="store_true", help="Opt A: cap tool results")
    parser.add_argument("--summarize", action="store_true", help="Opt B: compress history")
    parser.add_argument("--route", action="store_true", help="Opt C: cheap model routing")
    args = parser.parse_args()

    flags = OptimizationFlags(
        truncate_tool_results=args.truncate,
        summarize_history=args.summarize,
        route_models=args.route,
    )
    config_label = args.config or flags.label

    summary = run_benchmark(
        config_label, args.label or config_label, args.quiet, flags
    )

    print("\n" + "=" * 62)
    print(f"CONFIG: {summary['config']}  ({summary['description']})")
    print("=" * 62)
    print(f"  turns            {summary['turns']}")
    print(f"  api calls        {summary['api_calls']}")
    print(f"  input tokens     {summary['input_tokens']:,}")
    print(f"  output tokens    {summary['output_tokens']:,}")
    print(f"  TOTAL COST       ${summary['total_cost_usd']:.6f}")
    print(f"  COST PER TURN    ${summary['cost_per_turn_usd']:.6f}")
    print(
        f"  RECALL           {summary['recall_passed']}/{summary['recall_total']} passed"
    )
    print(f"  models           {summary['per_model_calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
