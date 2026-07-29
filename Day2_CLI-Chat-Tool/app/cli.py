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

import sys

import groq

from app.api import ChatError, run_turn
from app.config import Config
from app.conversation import Conversation
from app.costlog import CostLogger

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
          /exit  quit and write the session summary
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


def main() -> int:
    try:
        cfg = Config()
    except KeyError as exc:
        # Fail fast with an actionable message rather than a bare traceback.
        print(f"Missing required environment variable: {exc}", file=sys.stderr)
        print("Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1

    client = groq.Groq(api_key=cfg.groq_api_key)
    conversation = Conversation(SYSTEM_PROMPT, transcript_path="logs/transcript.jsonl")
    cost_logger = CostLogger(cfg.cost_log_path, config_label="baseline")

    print(_BANNER)
    print(f"model: {cfg.chat_model}")
    print(
        "search: Tavily + DuckDuckGo fallback"
        if cfg.tavily_api_key
        else "search: DuckDuckGo only (no TAVILY_API_KEY set)"
    )
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
