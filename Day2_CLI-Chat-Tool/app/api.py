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
from dataclasses import dataclass
from typing import Any, Callable

import groq

from app.conversation import Conversation
from app.costlog import CostLogger
from app.pricing import compute_cost
from app.tools import TOOL_SCHEMAS, run_tool

# Stops a pathological loop where the model calls tools forever. Each iteration
# is a paid API call, so this is a cost guard as much as a liveness guard.
_MAX_TOOL_ITERATIONS = 8


class ChatError(RuntimeError):
    """A turn failed in a way the user should be told about."""


@dataclass
class TurnResult:
    text: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


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


def run_turn(
    client: groq.Groq,
    conversation: Conversation,
    cost_logger: CostLogger,
    cfg: Any,
    turn_index: int,
    model: str | None = None,
    on_text: Callable[[str], None] | None = None,
) -> TurnResult:
    """Run one user turn to completion, including any tool calls.

    Assumes the user message has already been appended to `conversation`.
    Raises ChatError on unrecoverable API failure; the caller rolls back.
    """
    model = model or cfg.chat_model
    emit = on_text or (lambda chunk: print(chunk, end="", flush=True))

    api_calls = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    final_text = ""

    for iteration in range(_MAX_TOOL_ITERATIONS):
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=conversation.to_api_messages(),
                tools=TOOL_SCHEMAS,
                max_tokens=cfg.max_tokens,
                stream=True,
                # NOTE: no stream_options here. The OpenAI-style
                # stream_options={"include_usage": True} is not a named
                # parameter in groq 0.31.1, and it is not needed: Groq attaches
                # a `usage` object to the final chunk of a stream by default
                # (verified 2026-07-29 against llama-3.3-70b-versatile).
                # We read it in the loop below. If a future SDK version stops
                # doing this, _usage_tokens() returns zeros and the cost log
                # shows 0-token rows rather than crashing.
            )
        except groq.AuthenticationError as exc:
            # Not transient. Retrying will fail identically.
            raise ChatError(f"Authentication failed - check GROQ_API_KEY. ({exc})") from None
        except groq.RateLimitError as exc:
            raise ChatError(
                f"Rate limited by the API. Wait a moment and try again. ({exc})"
            ) from None
        except groq.BadRequestError as exc:
            # Usually a malformed history, e.g. an orphaned tool call.
            raise ChatError(f"The API rejected this request. ({exc})") from None
        except groq.APIConnectionError as exc:
            raise ChatError(f"Could not reach the API - check your connection. ({exc})") from None
        except groq.APIStatusError as exc:
            raise ChatError(f"API error {exc.status_code}. ({exc})") from None

        # --- consume the stream ---------------------------------------------
        text_parts: list[str] = []
        # tool_calls arrive fragmented across chunks: the id and name come
        # first, then arguments stream in as JSON string deltas. Reassemble
        # them by index before anything can be executed.
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage = None
        printed_any = False

        try:
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

        except groq.APIError as exc:
            # The stream died mid-flight. Partial text may already be on screen.
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

            # Exactly one tool message per tool_call id.
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": result,
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
