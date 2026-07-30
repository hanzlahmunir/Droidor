# Day 2 — CLI Chat Tool

A command-line chat app built directly on the Groq API. Streaming output,
multi-turn memory, three working tools, and per-call cost logging to a file.

No LangChain, no agent framework — the API loop is written by hand.

---

## Quick start

```bash
cp .env.example .env             # then paste your keys into .env
docker compose up                # builds, then verifies key + API reachability
docker compose run --rm chat     # starts the chat
```

### Reproducing the cost comparison

The before/after numbers are a flag, not a code edit:

```bash
docker compose run --rm chat --mode simple   # "before" - no optimisations
docker compose run --rm chat                 # "after"  - the default
```

Run the same conversation in each and compare `/cost`. To attribute a single
change (this is how the per-lever numbers in [docs/COST.md](docs/COST.md) were
measured):

```bash
docker compose run --rm chat --no-routing    # tool-result caps only
docker compose run --rm chat --no-truncate   # cheap-model routing only
docker compose run --rm chat --summarize     # + history summarisation (off by default)
```

The active configuration is printed in the banner, so a stale image is
obvious:

```
mode:   optimized
opts:   tool-result caps, cheap-model routing
```

`docker compose up` runs a preflight check: it builds the image, confirms your
API key works with a live call, and prints the command to start chatting.

Type `/exit` to quit, or `/cost` at any time to see the session cost so far.

> **Why two commands and not just `up`?**
>
> `docker compose up` cannot host an interactive prompt. It runs Compose's
> log-multiplexing view — the one that prefixes each line with
> `day2-chat  | ` — which *displays* container output but never forwards your
> keystrokes. A chat started that way prints its banner and then silently
> ignores everything you type. `stdin_open`, `tty` and `attach` do not change
> this; they configure the container, not what `up` does with your keyboard.
>
> `docker compose run` attaches your terminal directly, the way
> `docker run -it` does, which is what a REPL needs.
>
> Day 1 was a server: it listened on a port and needed no terminal, so `up`
> was the right command there. This is a REPL, so it is not. Rather than let
> `up` start a chat that appears to work but eats your input, it runs the
> preflight check and points you at the command that does work.

> **Only `GROQ_API_KEY` is required.** Get one free at
> [console.groq.com/keys](https://console.groq.com/keys). `TAVILY_API_KEY` is
> optional — without it, web search falls back to DuckDuckGo, which needs no
> key at all.

---

## What it does

| Feature | How |
|---|---|
| **Streaming** | Tokens print as they arrive, not in one block at the end |
| **Multi-turn memory** | Full history is resent each turn (the API is stateless), so it remembers earlier messages |
| **3 tools** | `calculator`, `web_search`, `fetch_url` |
| **Cost logging** | Every API call is appended to `logs/cost_log.jsonl`, with a session summary on exit |
| **Never crashes** | Tool errors, API errors and interrupts are all handled; the prompt always comes back |

---

## Trying it out

### The calculator

Just ask for arithmetic. The model calls the tool rather than doing mental
maths, and you will see the `[tool] calculator...` line as it runs.

```
you > What is 1847 * 293?
you > What is (18500 / 37) + 962?
```

The calculator **never uses `eval()`** — it parses the expression into an AST
and walks it with a strict allowlist of arithmetic operations.

To see that guard actually fire, use `/tool`, which calls a tool directly with
no model in the loop:

```
you > /tool calculator {"expression": "__import__('os').system('echo pwned')"}
  [tool] calculator -> Error: Unsupported expression element: Call

you > /tool calculator {"expression": "2**999999999"}
  [tool] calculator -> Error: Exponent too large (max 1000); refusing to evaluate.
```

> **Why `/tool` exists.** Asking the *chat* to compute something malicious
> usually makes the model refuse on its own — so the tool is never called and
> the guard is never exercised. That is the right outcome for the wrong
> reason: a model refusal is a soft layer that can be prompted around, and it
> proves nothing about the hard guard underneath. `/tool` bypasses the model
> so the allowlist is what answers. It costs nothing — no API call is made.

The second example is blocked because a huge exponent is not an error at all:
Python would try to allocate the number and hang the process, with no
exception to catch. That is a denial of service reachable from one message.

### Web search and fetch

```
you > Search the web for what the Model Context Protocol is
you > Find the latest Python release and tell me what changed
```

The model typically chains the two tools: `web_search` to find candidates,
then `fetch_url` to read the most promising one in full.

`fetch_url` is guarded against SSRF, since the model chooses the URL. Same
caveat as above — the model will usually refuse before the tool is reached, so
use `/tool` to exercise the guard itself:

```
you > /tool fetch_url {"url": "http://169.254.169.254/latest/meta-data/"}
  [tool] fetch_url -> Error: Blocked: '169.254.169.254' resolves to non-public address 169.254.169.254.

you > /tool fetch_url {"url": "file:///etc/passwd"}
  [tool] fetch_url -> Error: Blocked scheme 'file'; only http and https are allowed.
```

That first address is the cloud instance-metadata endpoint, which serves IAM
credentials to anything that can reach it. The guard resolves the hostname to
an IP *first*, because a perfectly public-looking domain can have a DNS record
pointing at a private address — checking the hostname string is not enough.

### Memory across turns

```
you > My name is Hanzlah and my employee ID is 4471.
you > What is 15 * 15?
you > Search for what MCP is.
you > What is my employee ID?
```

The last turn should recall `4471` despite the unrelated turns in between.

### Cost

```
you > /cost
```

Shows turns, API calls, tokens in/out, session total and cost per turn.
The same data lands in `logs/cost_log.jsonl` — one JSON object per API call,
so a turn that used two tools is visible as three separate rows.

> **Note on the numbers.** Groq's free tier bills $0. The figures here are
> *modelled* cost — what the session would cost at published paid rates —
> computed locally from the token counts the API returns. They are not billing
> data, and the README says so deliberately.

---

## Other commands

```bash
docker compose run --rm tests        # offline test suite (66 tests, no API key needed)
docker compose run --rm benchmark    # replay the fixed 10-turn cost benchmark
docker compose down                  # stop and clean up
```

> **After editing any source file, rebuild:** `docker compose build chat`.
> Compose reuses the existing image, so an edit that isn't rebuilt runs the
> *old* code with no warning. This actually happened: a session ran against a
> pre-optimisation image, reported baseline cost, and sent every call to the
> expensive model. The banner now prints the active config (`opts: ...`) as a
> check — if it doesn't match what you expect, the image is stale.

Logs are written to `./logs/` on the host, so they survive `docker compose down`.

### Running without Docker

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m app.cli
```

---

## Project layout

```
app/
  cli.py           REPL. Outermost error guard + history rollback.
  api.py           The API loop: streaming, tool-call handling, retries.
  conversation.py  Hybrid context store (live list + append-only transcript).
  optimize.py      Cost optimisations, each independently switchable.
  costlog.py       Per-call cost records -> JSONL.
  pricing.py       Model rate table + cost arithmetic.
  config.py        Environment configuration.
  tools/
    calculator.py  AST allowlist evaluator (never eval()).
    fetch_url.py   SSRF-guarded page fetcher.
    web_search.py  Tavily primary, DuckDuckGo fallback.
benchmark.py       Fixed 10-turn transcript for cost measurement.
compare.py         Runs every config N times and reports means.
docs/COST.md       Before/after cost analysis and what caused each change.
```

---

## How errors are handled

Three layers, each catching a different class of failure:

1. **Tool errors** (`tools/__init__.py`) — a failing tool returns an error
   *string*, which goes back to the model as a normal tool result. The model
   reads "Error: timed out" and adapts. Nothing propagates.
2. **API errors** (`api.py`) — typed by cause. Rate limits and connection
   failures are reported as retryable; auth failures are not. A model-side
   failure to emit valid tool-call JSON is retried automatically (it is
   transient, and happens often enough to matter).
3. **The REPL** (`cli.py`) — anything unanticipated prints
   *"Something went wrong. Please try again in a moment."* and returns to the
   prompt, **and rolls conversation history back** to its pre-turn state.

That rollback is the subtle one. A turn that dies between recording a tool call
and recording its result leaves history malformed, and then *every later
request* is rejected — the chat would appear to work, then fail permanently.

---

## Cost optimisation

| | cost/turn |
|---|---|
| Before — full history, no optimisations | $0.000275 |
| After — per-tool caps + cheap-model routing | **$0.000218** (−21%) |

Memory recall stayed 3/3 throughout. Both figures come from runs with matching
API call counts — that control matters, because call count correlates 0.74
with cost and varies run to run on identical input, independently of
configuration.

The brief asked for 50%. This is 21%, and
[docs/COST.md](docs/COST.md) explains why 50% is not reachable on this
workload with these levers: routing has a hard 30% ceiling (the cheap model is
exactly 2× cheaper and 41% of tokens are on tool turns that must stay on the
capable model), the cheapest available model fails recall 2/6 and is
unusable, and summarisation needs ~10 further turns per invocation to break
even.

Prompt caching *is* available on these models (automatic, 50% off cached
input) — an earlier version of this README said otherwise and was wrong. It is
still not claimed as a lever, because the `cached_tokens` usage field is not
exposed on this account and its cost effect could not be measured. See
[docs/CACHING.md](docs/CACHING.md), including the control run that overturned
a false positive.

Full per-change attribution, the two bugs found while measuring, and what
would be needed to reach 50%: [docs/COST.md](docs/COST.md).
