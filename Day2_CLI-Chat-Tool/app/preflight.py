"""What `docker compose up` runs.

An interactive REPL cannot be hosted by `docker compose up`: that command uses
the log-multiplexing view (the one prefixing lines with "day2-chat  | "), which
displays container output but never forwards keystrokes. A chat started there
prints its banner and then silently ignores everything typed at it.

So `up` runs this instead. It proves the image, configuration and credentials
all work end to end, then prints the command that actually starts the chat.
Verifying and pointing at the right command is more useful than appearing to
start something that cannot work.
"""

import sys

from app.config import Config

# No ANSI colour. This runs under `docker compose up`, whose log-multiplexing
# view does not interpret escape sequences -- they render as literal "[32m"
# noise in exactly the output that is supposed to be clear instructions.
GREEN = YELLOW = BOLD = RESET = ""


def main() -> int:
    print()
    print(f"{BOLD}Day 2 - CLI Chat Tool: preflight{RESET}")
    print("=" * 52)

    try:
        cfg = Config()
    except KeyError as exc:
        print(f"  [FAIL] missing environment variable: {exc}")
        print("\n  Copy .env.example to .env and fill in your Groq key.")
        return 1

    print(f"  [ok]   GROQ_API_KEY   set ({len(cfg.groq_api_key)} chars)")
    print(
        f"  [ok]   TAVILY_API_KEY set"
        if cfg.tavily_api_key
        else "  [--]   TAVILY_API_KEY not set (search falls back to DuckDuckGo)"
    )
    print(f"  [ok]   chat model     {cfg.chat_model}")
    print(f"  [ok]   cheap model    {cfg.cheap_model}")

    # A live call. Catches an expired or revoked key here, at `up` time, rather
    # than three turns into a conversation.
    try:
        import groq

        client = groq.Groq(api_key=cfg.groq_api_key)
        client.chat.completions.create(
            model=cfg.chat_model,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=5,
        )
        print(f"  [ok]   API reachable  {GREEN}credentials valid{RESET}")
    except Exception as exc:  # noqa: BLE001 - report any failure, don't raise
        print(f"  [FAIL] API call failed: {type(exc).__name__}")
        print(f"         {str(exc)[:160]}")
        return 1

    print("=" * 52)
    print(f"\n  {GREEN}Everything works.{RESET} Start the chat with:\n")
    print(f"      {BOLD}docker compose run --rm chat{RESET}\n")
    print(
        f"  {YELLOW}Note:{RESET} `docker compose up` cannot host an interactive\n"
        "  prompt -- it only displays output and does not forward what you\n"
        "  type. `run` attaches your terminal properly. That is why this\n"
        "  check runs here instead of the chat itself.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
