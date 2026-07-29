# Review notes — "why is this line here / what breaks if I change it"

Prep for the line-by-line review. Every answer below is something that was
measured or hit during the build, not reasoning after the fact.

---

## Tools

**Q: Why not just use `eval()` in the calculator? It's one line.**

The expression string is written by the model, and the model can be influenced
by any text in the conversation — including a web page `fetch_url` just
retrieved. `eval('__import__("os").system("rm -rf /")')` is a valid Python
expression. The AST walker is an *allowlist*: unknown node types are rejected
by default, so new syntax cannot silently open a hole. Tested against 8 attack
strings in `tests/test_calculator.py`.

**Q: What breaks if I remove the `_MAX_EXPONENT` check?**

`2**999999999` stops being an error and becomes a hang — Python tries to
allocate the number. No exception to catch, no timeout, the CLI just freezes.
It's a denial of service reachable from a single chat message.

**Q: Why check the resolved IP in `fetch_url` instead of just the hostname?**

Because hostname checks don't work. `http://localhost` is obvious, but a
public-looking domain can have a DNS record pointing at `127.0.0.1` or
`169.254.169.254`. So we resolve first, then check every returned address —
a hostname can return both a public and a private A record.

**Q: Why not use `follow_redirects=True`?**

It defeats the guard entirely. A public URL can 302 to `http://127.0.0.1`, and
httpx would follow it transparently. Redirects are followed manually so every
hop is re-validated.

**Q: What breaks if a tool raises instead of returning an error string?**

The chat dies. That's the brief's explicit rule. `run_tool()` is the single
choke point where any exception becomes a string that goes back to the model
as a normal tool result — the model reads "Error: timed out" and adapts. The
bare `except Exception` there is deliberate and is the one place in the
codebase where it's correct.

---

## The API loop

**Q: Why append `response.content` wholesale instead of just the text?**

The assistant message must carry its `tool_calls`. Append only the text and
the tool call is lost, the tool results below it are orphaned, and the next
request is rejected.

**Q: What breaks if `conversation.rollback()` is removed?**

This is the subtlest bug in the project. A turn that fails between appending
an assistant `tool_call` and appending its matching `tool_result` leaves
history malformed. Every *subsequent* request then 400s — the chat appears to
work, then fails permanently, and the error surfaces nowhere near the cause.
`tests/test_conversation_and_optimize.py::test_rollback_removes_orphaned_tool_call`
guards it.

**Q: Why retry on a 400? Aren't those permanent?**

Usually. But Groq returns 400 for two different things: a genuinely malformed
request (permanent), and the model failing to emit valid tool-call JSON on
this sampling attempt (transient — retrying the identical payload succeeds).
Measured at ~1 call in 6 on `llama-3.3-70b-versatile`. We classify by message
marker, not exception type, because the *same* failure arrives as
`BadRequestError` from the initial call and as a bare `APIError` from
mid-stream.

**Q: Why is `_MAX_TOOL_ITERATIONS` 8?**

It's a cost guard as much as a liveness guard — each iteration is a paid API
call. Without it a model that keeps calling tools bills indefinitely.

---

## Cost

**Q: Where does the cost number come from? Groq doesn't return dollars.**

It returns token counts; `pricing.py` holds the rate table and computes cost
locally. Rates verified against groq.com/pricing on 2026-07-29 — I had three
of five wrong from memory before checking. Free-tier spend is $0, so every
figure is explicitly *modelled* cost, not billing data, and the README says so.

**Q: Why per-call rows in the log instead of per-turn?**

A turn using two tools makes three API calls. Logging per turn would hide
that, and the multi-call turns are exactly where the cost is. `turn_index` +
`call_index` keep them attributable.

**Q: Why is `cost_per_turn` divided by turns and not calls?**

Because the brief asks for cost per *turn*. A turn that used three tools is
still one turn — dividing by calls would make an expensive turn look cheap.
Tested explicitly.

**Q: Why is summarisation off by default when it's implemented?**

Measured as a net loss at this session length: ~$0.000229 overhead per
summarisation against ~$0.000023/turn saving, so it needs ~10 further turns
per invocation to break even. At the original 1,500-token trigger it fired 3
times in 10 turns and turned a 16% win into a 68% loss. Kept in the codebase
because the economics invert on long sessions; trigger raised to 6,000.

**Q: The tool-result cap is per tool. Why not one number?**

A single 800-char cap measured *worse than baseline* ($0.000312 vs
$0.000275). Truncating a 4,662-char `fetch_url` result removed what the model
needed, so it re-fetched three more pages — turn 4 went from 2 API calls to 6.
Truncating below what the current turn needs doesn't save money, it relocates
the cost into retries.

**Q: Why not use the cheapest model for routing?**

`llama-3.1-8b-instant` is 3× cheaper on input and 7.5× on output, which would
lift the routing ceiling from 30% to ~47%. Measured on the recall turns the
router would send it: **2/6 correct**, plus a tool-generation error on a turn
needing no tool. `gpt-oss-20b` scored 6/6. Failing the memory requirement to
save a fraction of a cent is the wrong trade.

**Q: Why only 21% when the brief asked for 50%?**

Ceiling analysis in `docs/COST.md`. Routing caps at 30% (cheap model is
exactly 2× cheaper; 41% of tokens are on tool turns that must stay capable),
the cheapest model fails recall, and summarisation can't pay back at 10 turns.
Prompt caching would close it — ~90% off cached input — but Groq doesn't offer
it on the gpt-oss models. The honest answer is that 50% needs either a longer
session, a cheaper-and-capable small model, or a provider with caching.

---

## Measurement

**Q: How do you know the 21% is real and not noise?**

Because it initially wasn't. A single run showed truncation at −16%; the
aggregate across all runs showed −1%. Neither was right. Across 20 ten-turn
runs, **API call count correlates 0.739 with cost per turn** — and call count
is set by how many times the model decides to search, which varies on
identical input. Averaging across different call counts compares search luck,
not configuration. Every quoted number is from runs with matching call counts,
and `compare.py` prints that grouping.

**Q: Why does the benchmark score recall as well as cost?**

Because cost-cutting and memory pull against each other, and the lead tests
recall by asking about earlier turns. A config that halves cost but forgets
the user's employee ID is a downgrade. It caught a real regression: a summary
truncated at `max_tokens=400` cut off mid-line at `- Preference:`, destroying
exactly the fact the next turn asked for.

**Q: Anything the tests don't cover?**

Yes, and deliberately: the live API loop. CI has no key, so the 66 tests are
all offline — the calculator allowlist, SSRF guards, cost arithmetic, rollback
and the optimisation helpers. The API loop is verified by `benchmark.py`
against the real API, run locally with results committed under `docs/`. Three
of the bugs found today (transient tool-call failures, the Windows
UnicodeEncodeError crash, the wrong model choice) would not have been caught
by any unit test.

---

## Docker

**Q: Why isn't `docker compose up` the only command, like Day 1?**

Because `up` cannot host an interactive REPL, and I confirmed this by running
it. `up` uses Compose's log-multiplexing view — the one prefixing lines with
`day2-chat  | ` — which displays output but never forwards keystrokes. The
chat prints its banner and ignores everything typed. `stdin_open`, `tty` and
`attach` configure the *container*, not what `up` does with your keyboard.
`docker compose run --rm chat` attaches the terminal properly.

Day 1 was a server: it listened on a port and needed no terminal, so `up` was
right there. Rather than let `up` start a chat that silently eats input, it
runs a preflight service that verifies the key with a live API call and prints
the command that works.

**Q: Why `PYTHONUNBUFFERED=1`?**

Without it Python block-buffers stdout when it isn't a TTY, so streamed tokens
arrive in one burst at the end — which defeats the streaming feature entirely
inside Docker.
