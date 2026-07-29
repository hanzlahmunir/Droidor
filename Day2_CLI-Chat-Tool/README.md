# Day 2 — CLI Chat Tool

A command-line chat app built directly on the Groq API. Streaming output,
multi-turn memory, three working tools, and per-call cost logging to a file.

No LangChain, no agent framework — the API loop is written by hand.

---

## Quick start

```bash
cp .env.example .env      # then paste your keys into .env
docker compose up
```

That is the whole setup. `docker compose up` builds the image and drops you
straight into an interactive chat.

Type `/exit` to quit, or `/cost` at any time to see the session cost so far.

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
and walks it with a strict allowlist of arithmetic operations. To see the guard
working, ask it to compute something malicious:

```
you > Calculate __import__("os").system("echo pwned")
you > What is 2 ** 999999999?
```

Both come back as a handled error and the chat continues. The first is blocked
because `Call` is not an allowlisted node type; the second because a huge
exponent would hang the process while allocating (a denial of service, not a
crash you could catch).

### Web search and fetch

```
you > Search the web for what the Model Context Protocol is
you > Find the latest Python release and tell me what changed
```

The model typically chains the two tools: `web_search` to find candidates,
then `fetch_url` to read the most promising one in full.

`fetch_url` is guarded against SSRF, since the model chooses the URL. Try:

```
you > Fetch http://169.254.169.254/latest/meta-data/
you > Fetch http://localhost:8080/
```

Both are refused. That first address is the cloud instance-metadata endpoint,
which serves IAM credentials to anything that can reach it — the guard resolves
the hostname to an IP first, because a perfectly public-looking domain can
resolve to a private address.

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

See [docs/COST.md](docs/COST.md) for the measured before/after numbers and the
attribution of each change.
