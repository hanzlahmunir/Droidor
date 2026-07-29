"""The chat loop: streaming + manual tool-call handling.

Written by hand against the Groq SDK -- no LangChain, no agent framework, per
the brief. The loop shape is:

    send(history + tools)
      -> stream the reply, printing tokens as they arrive
      -> finish_reason == "tool_calls"?
           yes: append the assistant message (WITH its tool_calls),
                run each tool, append one tool-result message per call,
                loop again
           no:  done, this is the final answer

Two details that are easy to get wrong and will 400 the next request:
  - The assistant message must be appended INCLUDING its tool_calls. Appending
    only the text loses the call and orphans the results.
  - Every tool_call id must get exactly one matching tool-result message.

ERROR HANDLING LAYER 2 of 3: API-level failures are caught by type here.
Rate limits and 5xx are transient (the SDK already retries with backoff);
auth and 400s are not, so they are reported differently rather than retried.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

import groq

from app.conversation import Conversation
from app.costlog import CostLogger
from app.optimize import (
    OptimizationFlags,
    should_use_cheap_model,
    summarize_if_needed,
    truncate_tool_result,
)
from app.pricing import compute_cost
from app.tools import TOOL_SCHEMAS, run_tool

# Stops a pathological loop where the model calls tools forever. Each iteration
# is a paid API call, so this is a cost guard as much as a liveness guard.
_MAX_TOOL_ITERATIONS = 8

# Retries for the specific transient failure described below. Measured at
# roughly 1 call in 6 on llama-3.3-70b-versatile with three tools attached
# (2026-07-29), so a 10-turn session would almost always hit it at least once.
_MAX_GENERATION_RETRIES = 3

# Groq reports two very different situations through its error types:
#
#   (a) a genuinely malformed request -- e.g. history containing a tool_call
#       with no matching tool result. Retrying is pointless; it fails forever.
#
#   (b) the MODEL failed to emit valid tool-call JSON on this attempt. The
#       request was fine. Retrying the identical payload usually succeeds,
#       because generation is sampled and the next sample is well-formed.
#
# Treating (b) as permanent kills the session on a recoverable hiccup;
# treating (a) as retryable burns three calls to fail anyway.
#
# The exception TYPE cannot distinguish them, and this is the subtle part:
# the same underlying failure surfaces as BadRequestError when it happens on
# the initial call, but as a bare APIError when it happens partway through
# consuming the stream (verified 2026-07-29). So we classify on the message
# marker and check both types.
_RETRYABLE_GENERATION_MARKER = "failed to call a function"


def _is_retryable_generation_error(exc: Exception) -> bool:
    """True for case (b) above: model-side tool-call generation failure."""
    return _RETRYABLE_GENERATION_MARKER in str(exc).lower()


class ChatError(RuntimeError):
    """A turn failed in a way the user should be told about."""


@dataclass
class TurnResult:
    text: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _default_emit(chunk: str) -> None:
    """Print a streamed chunk, surviving terminals that cannot encode it.

    On Windows the console defaults to cp1252, which cannot represent emoji or
    most non-Latin text. The model emits both freely, and an uncaught
    UnicodeEncodeError here would kill the chat from inside the PRINT path --
    defeating the never-crash guarantee at the last possible step.

    cli.py reconfigures stdout to UTF-8 at startup, which fixes this properly.
    This fallback covers callers that bypass cli.py (benchmark.py, tests) and
    any terminal where reconfiguration is not possible: unencodable characters
    are replaced rather than raising.
    """
    try:
        print(chunk, end="", flush=True)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(
            chunk.encode(encoding, errors="replace").decode(encoding),
            end="",
            flush=True,
        )


def _usage_tokens(usage: Any) -> tuple[int, int]:
    """Pull (prompt, completion) token counts off a usage object.

    Groq returns usage on the final streamed chunk. If it is ever missing we
    return zeros rather than crashing -- an unlogged turn is a smaller problem
    than a dead chat -- and the zeros are visible in the log as a symptom.
    """
    if usage is None:
        return 0, 0
    return (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
    )


def _stream_completion(
    client: groq.Groq,
    conversation: Conversation,
    cfg: Any,
    model: str,
    emit: Callable[[str], None],
) -> tuple[list[str], dict[int, dict[str, Any]], str | None, Any, bool]:
    """Make one streaming request and consume it fully.

    Returns (text_parts, tool_calls, finish_reason, usage, printed_any).
    Lets groq exceptions propagate so the caller can classify and retry them.
    """
    stream = client.chat.completions.create(
        model=model,
        messages=conversation.to_api_messages(),
        tools=TOOL_SCHEMAS,
        max_tokens=cfg.max_tokens,
        stream=True,
        # NOTE: no stream_options here. The OpenAI-style
        # stream_options={"include_usage": True} is not a named parameter in
        # groq 0.31.1, and it is not needed: Groq attaches a `usage` object to
        # the final chunk of a stream by default (verified 2026-07-29 against
        # llama-3.3-70b-versatile). If a future SDK version stops doing this,
        # _usage_tokens() returns zeros and the cost log shows 0-token rows
        # rather than crashing.
    )

    text_parts: list[str] = []
    # tool_calls arrive fragmented across chunks: the id and name come first,
    # then arguments stream in as JSON string deltas. Reassemble them by index
    # before anything can be executed.
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    usage = None
    printed_any = False

    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage

        if not chunk.choices:
            continue

        choice = chunk.choices[0]
        delta = choice.delta

        if choice.finish_reason:
            finish_reason = choice.finish_reason

        if delta.content:
            text_parts.append(delta.content)
            emit(delta.content)
            printed_any = True

        for tc in delta.tool_calls or []:
            slot = tool_calls.setdefault(
                tc.index, {"id": "", "name": "", "arguments": ""}
            )
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                slot["arguments"] += tc.function.arguments

    return text_parts, tool_calls, finish_reason, usage, printed_any


def run_turn(
    client: groq.Groq,
    conversation: Conversation,
    cost_logger: CostLogger,
    cfg: Any,
    turn_index: int,
    model: str | None = None,
    on_text: Callable[[str], None] | None = None,
    flags: OptimizationFlags | None = None,
) -> TurnResult:
    """Run one user turn to completion, including any tool calls.

    Assumes the user message has already been appended to `conversation`.
    Raises ChatError on unrecoverable API failure; the caller rolls back.
    """
    flags = flags or OptimizationFlags()
    emit = on_text or _default_emit

    # --- Optimisation B: compress history BEFORE building this request, so
    # the saving applies to this turn and not only to later ones.
    summarize_if_needed(
        client, conversation, cfg, flags.summarize_history, cost_logger, turn_index
    )

    # --- Optimisation C: route easy turns to the cheaper model. Decided from
    # the last user message, using free string heuristics.
    if model is None:
        last_user = next(
            (
                m.get("content") or ""
                for m in reversed(conversation.messages)
                if m.get("role") == "user"
            ),
            "",
        )
        use_cheap = should_use_cheap_model(last_user, flags.route_models)
        model = cfg.cheap_model if use_cheap else cfg.chat_model

    api_calls = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    final_text = ""

    for iteration in range(_MAX_TOOL_ITERATIONS):
        # The request and the stream consumption are retried together: this
        # failure can surface either when the call is made or partway through
        # reading the stream, and both mean the same thing.
        for attempt in range(_MAX_GENERATION_RETRIES):
            try:
                text_parts, tool_calls, finish_reason, usage, printed_any = (
                    _stream_completion(client, conversation, cfg, model, emit)
                )
                break
            except groq.APIError as exc:
                # Checked FIRST, before any type-based dispatch, because this
                # failure arrives as BadRequestError from the initial call but
                # as a bare APIError from mid-stream. Only the message is
                # reliable across both.
                if _is_retryable_generation_error(exc):
                    if attempt == _MAX_GENERATION_RETRIES - 1:
                        raise ChatError(
                            "The model could not produce a valid tool call after "
                            f"{_MAX_GENERATION_RETRIES} attempts."
                        ) from None
                    # Retry the identical payload. Nothing has been appended to
                    # history yet, so there is no state to undo.
                    emit("\n  [retrying...] ")
                    continue

                # Everything else: classify by type, most specific first.
                # (BadRequestError/AuthenticationError/RateLimitError are all
                # subclasses of APIStatusError, which is a subclass of APIError,
                # so order matters here.)
                if isinstance(exc, groq.AuthenticationError):
                    raise ChatError(
                        f"Authentication failed - check GROQ_API_KEY. ({exc})"
                    ) from None
                if isinstance(exc, groq.RateLimitError):
                    raise ChatError(
                        f"Rate limited by the API. Wait a moment and try again. ({exc})"
                    ) from None
                if isinstance(exc, groq.BadRequestError):
                    raise ChatError(f"The API rejected this request. ({exc})") from None
                if isinstance(exc, groq.APIConnectionError):
                    raise ChatError(
                        f"Could not reach the API - check your connection. ({exc})"
                    ) from None
                if isinstance(exc, groq.APIStatusError):
                    raise ChatError(f"API error {exc.status_code}. ({exc})") from None
                raise ChatError(f"The response was interrupted. ({exc})") from None

        # --- account for this call ------------------------------------------
        api_calls += 1
        prompt_tokens, completion_tokens = _usage_tokens(usage)
        cost = compute_cost(model, prompt_tokens, completion_tokens)
        cost_logger.record(cost, turn_index=turn_index, call_index=iteration)
        total_in += prompt_tokens
        total_out += completion_tokens
        total_cost += cost.total_cost_usd

        assistant_text = "".join(text_parts)

        # --- no tools requested: this is the final answer --------------------
        if not tool_calls:
            conversation.append({"role": "assistant", "content": assistant_text})
            final_text = assistant_text
            if finish_reason == "length":
                # Truncated by max_tokens. Say so rather than letting the user
                # read a sentence that stops mid-word and assume a bug.
                notice = "\n\n[Reply truncated: hit the max_tokens limit.]"
                emit(notice)
                final_text += notice
            break

        # --- tools requested -------------------------------------------------
        ordered = [tool_calls[i] for i in sorted(tool_calls)]

        # Append the assistant turn WITH tool_calls. Dropping these orphans the
        # results below and makes the next request invalid.
        conversation.append(
            {
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"] or "{}",
                        },
                    }
                    for call in ordered
                ],
            }
        )

        if printed_any:
            emit("\n")

        for call in ordered:
            emit(f"  [tool] {call['name']}...")

            # Arguments are a JSON string built by the model, so malformed JSON
            # is a realistic failure -- handle it as a tool error, not a crash.
            try:
                args = json.loads(call["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                result = f"Error: could not parse tool arguments: {exc}"
            else:
                result = run_tool(call["name"], args, cfg)

            preview = result.replace("\n", " ")[:60]
            emit(f" {preview}{'...' if len(result) > 60 else ''}\n")

            # --- Optimisation A: cap what a tool result contributes to history.
            #
            # The next loop iteration rebuilds the request from `conversation`,
            # so the model sees this truncated text on THIS turn too -- not
            # just on later ones. That is a real quality tradeoff, not a free
            # win, and it is why the benchmark scores recall alongside cost.
            #
            # The saving is large because a tool result is not paid for once:
            # it is resent on every subsequent turn for the rest of the
            # session. In the baseline run one web_search result pushed turn 4
            # to 4,722 input tokens and kept turns 5-6 above 2,400.
            #
            # _TOOL_RESULT_MAX_CHARS is set to keep the head of the result,
            # where search engines and articles put the most relevant material.
            stored = truncate_tool_result(
                result, flags.truncate_tool_results, call["name"]
            )

            # Exactly one tool message per tool_call id.
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": stored,
                }
            )
    else:
        # Loop exhausted without a final answer.
        raise ChatError(
            f"Stopped after {_MAX_TOOL_ITERATIONS} tool rounds without finishing."
        )

    return TurnResult(
        text=final_text,
        api_calls=api_calls,
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=total_cost,
    )
