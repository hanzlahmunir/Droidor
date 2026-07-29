"""Cost optimisations, each independently switchable.

Every optimisation is a flag so the benchmark can measure them ONE AT A TIME
and attribute savings correctly. Turning them all on at once produces a single
number nobody can explain, which is exactly what the brief asks us to avoid.

Measured baseline (10-turn transcript, gpt-oss-120b, 2026-07-29):
    cost/turn $0.000400, input 21,959 tok (82% of cost), output 1,170 tok (18%)
    input grew 8.3x from turn 0 to turn 9

That shape dictates the order of attack: input dominates, so the levers are
about what goes into history and how long it stays there. Shortening replies
would be optimising the 18%.
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# A: tool-result truncation
# ---------------------------------------------------------------------------
# The single highest-leverage change, and the cheapest to implement.
#
# A web_search result is ~3,700 tokens. It enters history on the turn it is
# fetched -- and is then RESENT on every subsequent turn for the rest of the
# session. In the baseline run, turn 4's search inflated that turn to 4,722
# input tokens and kept turns 5 and 6 above 2,400.
#
# The model only needs the full text on the turn it reasons about it. Later
# turns need the gist. So we keep the head of the result (where search engines
# put the most relevant material) and drop the tail.
#
# PER-TOOL CAPS, set by measurement rather than by picking one round number.
#
# A single 800-char cap for everything was measured at $0.000312/turn -- WORSE
# than the $0.000273 baseline. Cause: truncating a 4,662-char fetch_url result
# to 836 chars removed the content the model needed, so it re-fetched three
# more pages and re-sent the whole growing history each time. Turn 4 went from
# 2 API calls to 6. The downstream saving was real (turns 6-9 dropped ~15%) but
# was swamped by the extra calls.
#
# The lesson generalises: truncating below what the current turn needs does not
# save money, it moves the cost into retries. So each tool gets a cap sized to
# what it actually returns:
#
#   web_search  ~2,470 chars: 5 results, each a title/URL/snippet. Cutting the
#               tail drops whole results, which is survivable -- the model
#               normally uses the first one or two.
#   fetch_url   up to 6,000 chars of page text. This is the one the model
#               reasons over in depth, so it keeps the largest budget.
#   calculator  ~20 chars. Never truncated; a cap here would be pointless.
_TOOL_RESULT_CAPS: dict[str, int] = {
    "web_search": 1600,
    "fetch_url": 3000,
}

# Applied to any tool not listed above.
_DEFAULT_TOOL_RESULT_CAP = 2000


# ---------------------------------------------------------------------------
# B: sliding window + fact-preserving summary
# ---------------------------------------------------------------------------
# Keep recent turns verbatim; compress older ones into one summary block.
#
# THE TENSION WITH MEMORY: the lead tests recall by asking about earlier turns.
# A summary that says "the user introduced themselves" fails that test. So the
# summariser is instructed to preserve concrete facts (names, IDs, numbers,
# preferences, decisions) and compress only conversational filler.
#
# Summarising COSTS an API call, so it is triggered by a token threshold rather
# than run every turn. On a short session it would be a net loss.
_SUMMARY_TRIGGER_TOKENS = 1500
_KEEP_RECENT_MESSAGES = 6

_SUMMARY_PROMPT = (
    "Compress the conversation below into a factual brief for an assistant "
    "that must answer questions about it later.\n\n"
    "MUST preserve, verbatim where possible:\n"
    "- names, IDs, numbers, dates, and any value the user stated about themselves\n"
    "- stated preferences, decisions, and constraints\n"
    "- conclusions reached, and results returned by tools\n\n"
    "MAY discard: greetings, acknowledgements, restatements, pleasantries, "
    "and the wording of explanations whose conclusion you have kept.\n\n"
    "Write terse bullet points. No preamble.\n\n"
    "CONVERSATION:\n"
)


# ---------------------------------------------------------------------------
# C: model routing
# ---------------------------------------------------------------------------
# Route easy turns to the cheaper model. gpt-oss-20b is 2x cheaper on both
# sides than gpt-oss-120b ($0.075/$0.30 vs $0.15/$0.60 per Mtok).
#
# THE ROUTING DECISION MUST BE FREE. Calling an LLM to classify difficulty
# would spend a call to save a call. These are string/length heuristics only.
_CHEAP_MODEL_MAX_INPUT_CHARS = 200

# Words suggesting the turn needs a tool or real reasoning -> use the big model.
_HARD_SIGNALS = (
    "calculate", "compute", "search", "find", "look up", "fetch", "url",
    "http", "www.", "explain", "why", "how does", "compare", "analyse",
    "analyze", "write", "code", "debug", "*", "/", "+", "%",
)


@dataclass(frozen=True)
class OptimizationFlags:
    """Which optimisations are active. Default = baseline (all off)."""

    truncate_tool_results: bool = False
    summarize_history: bool = False
    route_models: bool = False

    @property
    def label(self) -> str:
        """Short label for the cost log, so runs are distinguishable."""
        parts = []
        if self.truncate_tool_results:
            parts.append("trunc")
        if self.summarize_history:
            parts.append("summary")
        if self.route_models:
            parts.append("routing")
        return "+".join(parts) if parts else "baseline"


def truncate_tool_result(result: str, enabled: bool, tool_name: str = "") -> str:
    """Shorten a tool result before it is stored in history.

    Returns the result unchanged when disabled, so the baseline path is
    genuinely untouched rather than merely configured with a large limit.
    """
    if not enabled:
        return result

    cap = _TOOL_RESULT_CAPS.get(tool_name, _DEFAULT_TOOL_RESULT_CAP)
    if len(result) <= cap:
        return result

    kept = result[:cap]
    dropped = len(result) - cap
    # The marker matters: it tells the model the text was cut rather than
    # letting it assume the source simply ended there and re-fetching.
    return f"{kept}\n[... {dropped} characters truncated ...]"


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token count for threshold decisions.

    Deliberately an approximation (~4 chars/token). Calling the real
    count_tokens endpoint on every turn to decide whether to save tokens would
    be self-defeating; this only needs to be right enough to trip a threshold.
    """
    total_chars = 0
    for message in messages:
        content = message.get("content") or ""
        if isinstance(content, str):
            total_chars += len(content)
        for call in message.get("tool_calls") or []:
            total_chars += len(str(call))
    return total_chars // 4


def summarize_if_needed(
    client,
    conversation,
    cfg,
    enabled: bool,
    cost_logger=None,
    turn_index: int = -1,
) -> bool:
    """Compress older history into a factual summary. Returns True if it ran.

    Called BEFORE the turn's API request, so the compression benefits this turn
    rather than only later ones.

    The summarisation call is itself logged to the cost log. That is deliberate:
    hiding it would make the optimisation look better than it is, and the whole
    point of the exercise is an honest before/after.
    """
    if not enabled:
        return False

    messages = conversation.messages

    # Nothing to gain if there is barely any history to compress.
    if len(messages) <= _KEEP_RECENT_MESSAGES + 2:
        return False

    if estimate_tokens(messages) < _SUMMARY_TRIGGER_TOKENS:
        return False

    # Split at a safe boundary. A tool result must never be separated from the
    # assistant message carrying its tool_call, or the API rejects the history.
    split = len(messages) - _KEEP_RECENT_MESSAGES
    while split > 0 and messages[split].get("role") == "tool":
        split -= 1
    if split <= 0:
        return False

    older, recent = messages[:split], messages[split:]

    transcript_parts = []
    for message in older:
        role = message.get("role", "?")
        content = message.get("content") or ""
        if message.get("tool_calls"):
            names = ", ".join(
                c.get("function", {}).get("name", "?") for c in message["tool_calls"]
            )
            content = f"{content} [called tools: {names}]".strip()
        transcript_parts.append(f"{role}: {content}")

    try:
        response = client.chat.completions.create(
            model=cfg.cheap_model,  # summarising is itself an "easy" task
            messages=[
                {
                    "role": "user",
                    "content": _SUMMARY_PROMPT + "\n".join(transcript_parts),
                }
            ],
            # Generous on purpose. An earlier version used 400 and the summary
            # was cut off mid-line at "- Preference:" -- exactly where the
            # user's stated preferences would have been -- silently destroying
            # a fact the recall test then failed on. A summary that loses facts
            # is worse than no summary, and the tokens saved by a tight cap are
            # a rounding error next to the history it replaces.
            max_tokens=1200,
        )
    except Exception:  # noqa: BLE001 - a failed summary must not kill the turn
        # Fall back to uncompressed history: more expensive, still correct.
        return False

    summary_text = (response.choices[0].message.content or "").strip()
    if not summary_text:
        return False

    # If the model hit the cap anyway, the summary may be truncated mid-fact.
    # Discarding it costs one wasted call; keeping it silently loses memory.
    if response.choices[0].finish_reason == "length":
        conversation.record_event(
            {
                "event": "summary_discarded",
                "reason": "hit max_tokens, may be truncated mid-fact",
            }
        )
        return False

    if cost_logger is not None:
        from app.pricing import compute_cost

        usage = response.usage
        cost_logger.record(
            compute_cost(
                cfg.cheap_model,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            ),
            turn_index=turn_index,
            call_index=-1,  # -1 marks an overhead call, not a reply to the user
        )

    # Replace older turns with one user-role summary message. User role (not
    # system) because the system prompt lives outside this list and some models
    # ignore a second system message mid-conversation.
    summary_message = {
        "role": "user",
        "content": f"[Earlier conversation, condensed]\n{summary_text}",
    }
    conversation.messages[:] = [summary_message, *recent]

    # Mirror the summary to the transcript explicitly. This rewrite bypasses
    # Conversation.append(), so without this the summary would never be
    # recorded -- and a later recall failure would be undiagnosable, because
    # the very text the model was working from would be missing from the log.
    conversation.record_event(
        {
            "event": "history_summarized",
            "replaced_messages": len(older),
            "summary": summary_text,
        }
    )
    return True


def should_use_cheap_model(user_message: str, enabled: bool) -> bool:
    """Heuristic router: True if this turn looks cheap to answer.

    Conservative by design -- when unsure, use the capable model. A wrong
    "cheap" decision costs answer quality, which is a worse failure than a
    wrong "expensive" decision costing a fraction of a cent.
    """
    if not enabled:
        return False

    if len(user_message) > _CHEAP_MODEL_MAX_INPUT_CHARS:
        return False

    lowered = user_message.lower()
    return not any(signal in lowered for signal in _HARD_SIGNALS)
