"""Interactive REPL.

ERROR HANDLING LAYER 3 of 3: the outermost guard. Whatever happens inside a
turn -- a typed ChatError, or something nobody anticipated -- the REPL prints a
friendly message and returns to the prompt. The process does not die.

Two things this layer must do beyond printing a message:

  1. ROLL BACK HISTORY. A turn that fails between appending an assistant
     tool_call and appending the matching tool result leaves history malformed,
     and every subsequent request 400s. The chat would appear to "work" and
     then fail forever. Rolling back to the pre-turn snapshot prevents that.

  2. HANDLE Ctrl+C PER TURN. Interrupting a long stream should cancel that turn
     and return to the prompt, not tear down the session and lose the log.
"""

import argparse
import json
import sys

import groq

from app.api import ChatError, run_turn
from app.config import Config
from app.conversation import Conversation
from app.costlog import CostLogger
from app.optimize import OptimizationFlags
from app.tools import run_tool

SYSTEM_PROMPT = (
    "You are a concise, helpful CLI assistant. "
    "Use the calculator tool for arithmetic rather than computing mentally. "
    "Use web_search for current events or facts you are unsure of, then "
    "fetch_url to read a specific result. "
    "Remember details the user tells you and refer back to them when relevant. "
    "Keep answers brief unless asked to elaborate."
)

_GENERIC_ERROR = "\nSomething went wrong. Please try again in a moment."

_BANNER = """\
Day 2 - CLI Chat Tool
Tools: calculator, web_search, fetch_url
Commands: /cost  session cost so far
          /tool  call a tool directly, bypassing the model
          /exit  quit and write the session summary
"""

_TOOL_HELP = """\
  /tool <name> <json-args>   call a tool directly

  Why this exists: asking the model to run a malicious input usually makes it
  refuse on its own, so the tool is never called and the real guard is never
  exercised. That is the right outcome for the wrong reason -- the model's
  refusal is a soft layer, and it can be talked around. This calls the tool
  directly so the hard guard is what answers.

  examples:
    /tool calculator {"expression": "2+2"}
    /tool calculator {"expression": "__import__('os').system('echo pwned')"}
    /tool fetch_url {"url": "http://169.254.169.254/latest/meta-data/"}
    /tool web_search {"query": "model context protocol"}
"""


def _print_cost(logger: CostLogger) -> None:
    t = logger.totals
    print(
        f"\n  turns={t.turns}  api_calls={t.calls}  "
        f"in={t.input_tokens:,} out={t.output_tokens:,} tokens\n"
        f"  session=${t.cost_usd:.6f}  per_turn=${t.cost_per_turn_usd:.6f}"
    )
    if t.per_model_calls:
        breakdown = "  ".join(f"{m}={n}" for m, n in t.per_model_calls.items())
        print(f"  models: {breakdown}")


def _run_tool_directly(command: str, cfg: Config) -> None:
    """Handle `/tool <name> <json-args>` -- invoke a tool with no model involved.

    This makes the security guards demonstrable. Asking the chat to compute
    `__import__("os").system(...)` normally makes the MODEL refuse, so the
    calculator is never called and its AST allowlist is never exercised. The
    outcome looks right but proves nothing about the guard that actually
    matters, because a model refusal can be prompted around.

    Costs nothing: no API call is made.
    """
    parts = command.split(maxsplit=2)

    if len(parts) < 3:
        print(_TOOL_HELP)
        return

    _, name, raw_args = parts

    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"  could not parse arguments: {exc}")
        print('  expected e.g. /tool calculator {"expression": "2+2"}')
        return

    # run_tool never raises -- that is the layer-1 guarantee under test here.
    print(f"  [tool] {name} -> {run_tool(name, args, cfg)}")


def _force_utf8_stdout() -> None:
    """Make stdout/stderr UTF-8 so model output cannot crash the terminal.

    Windows consoles default to cp1252, which cannot encode emoji or most
    non-Latin scripts -- both of which the model produces unprompted. Without
    this, printing a single emoji raises UnicodeEncodeError from inside the
    print call and takes down the chat.

    errors="replace" is a second line of defence for anything still unmappable
    after the switch.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Redirected to a pipe that refuses reconfiguration; the
                # fallback in api._default_emit still applies.
                pass


def _parse_args() -> argparse.Namespace:
    """Command-line options.

    `--mode` exists so a reviewer can run the before/after cost comparison
    without editing source and rebuilding the image. Adopted from the
    co-intern's tool during peer review -- ours previously hardcoded the
    optimisations in this file, which made the comparison this project is
    *about* the hardest thing in it to reproduce.

    The individual --no-* flags allow attributing a single optimisation, which
    is how the per-change numbers in docs/COST.md were measured.
    """
    parser = argparse.ArgumentParser(
        description="Day 2 CLI chat tool (Groq API, hand-written loop)."
    )
    parser.add_argument(
        "--mode",
        choices=["simple", "optimized"],
        default="optimized",
        help=(
            "simple: full history, one model, untruncated tool results "
            "(the measured baseline). optimized (default): per-tool result "
            "caps + cheap-model routing."
        ),
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="optimized mode only: disable per-tool result caps",
    )
    parser.add_argument(
        "--no-routing",
        action="store_true",
        help="optimized mode only: keep every turn on the capable model",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help=(
            "enable history summarisation. OFF by default: measured as a net "
            "loss below ~20 turns (see docs/COST.md)."
        ),
    )
    return parser.parse_args()


def _flags_from_args(args: argparse.Namespace) -> OptimizationFlags:
    """Turn parsed arguments into the flag set used for the session."""
    if args.mode == "simple":
        # The baseline the cost work is measured against: nothing enabled.
        return OptimizationFlags()

    return OptimizationFlags(
        truncate_tool_results=not args.no_truncate,
        route_models=not args.no_routing,
        summarize_history=args.summarize,
    )


def main() -> int:
    _force_utf8_stdout()
    args = _parse_args()

    try:
        cfg = Config()
    except KeyError as exc:
        # Fail fast with an actionable message rather than a bare traceback.
        print(f"Missing required environment variable: {exc}", file=sys.stderr)
        print("Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1

    client = groq.Groq(api_key=cfg.groq_api_key)
    conversation = Conversation(SYSTEM_PROMPT, transcript_path="logs/transcript.jsonl")

    # Defaults (optimized mode) are the optimisations that measured as genuine
    # wins with recall intact: per-tool result caps (-16%) and cheap-model
    # routing (-22% combined), both verified at matched API call counts.
    #
    # Summarisation stays off unless --summarize: measured as a net loss on
    # sessions of this length (fixed ~$0.000229 overhead per summarisation
    # against ~$0.000023/turn saving, so it needs ~10 further turns to break
    # even). Kept because the economics invert on long sessions.
    #
    # See docs/COST.md for all of the above.
    flags = _flags_from_args(args)
    cost_logger = CostLogger(cfg.cost_log_path, config_label=flags.label)

    print(_BANNER)
    print(f"model:  {cfg.chat_model}")
    print(
        "search: Tavily + DuckDuckGo fallback"
        if cfg.tavily_api_key
        else "search: DuckDuckGo only (no TAVILY_API_KEY set)"
    )
    # Printed so a stale Docker image cannot silently run the wrong config.
    # A session was once run against an image built before optimisations were
    # enabled; it reported baseline cost and every call went to the expensive
    # model, with nothing on screen to indicate why. Now the active config is
    # visible in the first three lines.
    active = [
        name
        for name, on in (
            ("tool-result caps", flags.truncate_tool_results),
            ("cheap-model routing", flags.route_models),
            ("history summary", flags.summarize_history),
        )
        if on
    ]
    print(f"mode:   {args.mode}")
    print(f"opts:   {', '.join(active) if active else 'none (baseline)'}")
    print()

    turn_index = 0

    while True:
        try:
            user_input = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D / Ctrl+C at the prompt is a normal way to quit.
            print()
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            break

        if user_input == "/cost":
            _print_cost(cost_logger)
            continue

        if user_input.startswith("/tool"):
            _run_tool_directly(user_input, cfg)
            continue

        # Snapshot BEFORE any mutation, so a failure anywhere in the turn --
        # including partway through a tool round -- can be undone cleanly.
        marker = conversation.snapshot()
        conversation.append({"role": "user", "content": user_input})

        print("bot > ", end="", flush=True)

        try:
            run_turn(
                client=client,
                conversation=conversation,
                cost_logger=cost_logger,
                cfg=cfg,
                turn_index=turn_index,
                flags=flags,
            )
            print()
            cost_logger.mark_turn_complete()
            turn_index += 1

        except KeyboardInterrupt:
            # Cancel this turn only. History is rolled back so the abandoned
            # partial turn cannot corrupt the next request.
            conversation.rollback(marker)
            print("\n[cancelled]")

        except ChatError as exc:
            # Expected, typed failure. Show the specific reason -- it is
            # actionable (rate limited, bad key, no connection).
            conversation.rollback(marker)
            print(f"\n{exc}")
            print("Please try again in a moment.")

        except Exception as exc:  # noqa: BLE001 - the never-crash guarantee
            # Anything unanticipated. Generic message to the user, type name
            # retained so it is debuggable from the terminal.
            conversation.rollback(marker)
            print(_GENERIC_ERROR)
            print(f"[debug] {type(exc).__name__}: {exc}")

    summary = cost_logger.write_session_summary()
    print("\n--- session summary ---")
    _print_cost(cost_logger)
    print(f"\nCost log written to: {cost_logger.path}")
    print(f"Session id: {summary['session_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
