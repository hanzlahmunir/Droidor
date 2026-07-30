# Peer review — m-hamzaj/Cli-chat (Day 2)

Reviewed 2026-07-30 against a clone at `../partner-review-day2`. Everything
below was executed, not read off the source.

**Verdict: works, and is genuinely cheaper than ours — but the default mode
fails the memory requirement the lead said he would test, and `fetch_url` has
no SSRF protection.** Two must-fix items, both small.

---

## What works

| | |
|---|---|
| Runs in Docker | ✅ `docker compose run --rm chat` — same conclusion we reached about `up` |
| Streaming | ✅ |
| Tools | ✅ calculator returned 541171; fetch_url works |
| Cost logging to file | ✅ `logs/costs.jsonl`, one row per call, plus a session summary |
| Tests | ✅ 19 passing |
| CI | ✅ tests **and a Docker build check** — better than ours, we only run tests |
| Secrets | ✅ `.env.example` is a clean placeholder, `.env` gitignored |
| Errors don't crash | ✅ verified — every turn failed on an SDK mismatch and the REPL stayed alive |

**Cost: $0.000043/turn vs our $0.000218 — 5× cheaper.** That is a real result,
not a measurement artefact. It comes from routing to `llama-3.1-8b-instant`
($0.05/$0.08 per Mtok) where we route to `gpt-oss-20b` ($0.075/$0.30). See the
caveat below, though — the saving is bought with the memory requirement.

---

## Must fix 1 — `fetch_url` has no SSRF guard

`app/tools.py` accepts any URL the model produces, with no scheme allowlist and
no IP validation. Worse, a bare hostname is silently prefixed with `https://`,
so `localhost:8099` becomes a valid target.

Demonstrated live. I started a local HTTP server on `127.0.0.1:8099` serving a
file, then asked their tool to fetch it:

```
fetch_url('http://127.0.0.1:8099/secret.txt')
  -> "SECRET-INTERNAL-DATA-THAT-SHOULD-NOT-LEAK"     # contents returned
fetch_url('http://127.0.0.1:8099/')
  -> "Directory listing for / ... secret.txt"         # full listing
```

Ours, same target:

```
  -> Blocked: '127.0.0.1' resolves to non-public address 127.0.0.1.
```

The earlier "it's fine, those all error" reading is wrong: `169.254.169.254`
and `localhost` returned errors on my machine only because **nothing was
listening**. That is an accident of environment, not a defence. On any host
running an internal service — or any cloud VM, where `169.254.169.254` serves
IAM credentials — those requests succeed.

This matters because the URL is chosen by the model, which can be influenced by
the content of a page it previously fetched. It is attacker-reachable input.

**Fix** (~20 lines): allowlist `http`/`https`; `socket.getaddrinfo()` the host
and reject any address where `ipaddress.ip_address(...)` is private, loopback,
link-local or reserved; do not auto-prefix bare strings with `https://`. Ours
is in `app/tools/fetch_url.py` if useful. Checking the hostname *string* is not
enough — a public domain can have a DNS record pointing at `127.0.0.1`, which
is why the check has to be on the resolved IP.

---

## Must fix 2 — default mode fails memory recall

The lead explicitly said he would ask the bot about earlier turns. On the
default `--mode optimized`, it does not remember.

Same 7-turn transcript, both modes:

```
--mode optimized (llama-3.1-8b-instant)
  "What is my employee ID and which team am I on?"
    -> "I don't have any information about your employment or personal details."
  "Which database did I say I prefer?"
    -> "I don't retain any information from previous conversations."

--mode simple (llama-3.3-70b-versatile)
  -> "Your employee ID is 4471, and you are on the backend team."
  -> "You mentioned that your favorite database is Postgres."
```

**It is the model, not the history window.** The facts were in the context
sent — the 8B model has them and denies having them. This matches an
independent measurement I ran yesterday while choosing our own cheap tier:
`llama-3.1-8b-instant` scored **2/6** on recall questions versus **6/6** for
`gpt-oss-20b`. That result is why we did not use it, despite it being cheaper.

**Fix options**, cheapest first:
1. Add recall-style phrasings (`my name`, `my ID`, `what did I say`, `remember`,
   `earlier`) to `_COMPLEX_MARKERS` in `router.py`, so those turns go to 70B.
   Small cost increase, keeps the 8B saving everywhere else.
2. Switch the small model to `openai/gpt-oss-20b` (6/6 recall, ~2× the 8B price
   but still far below 70B).

Worth being explicit in the write-up either way: the 5× cost advantage is
partly bought by using a model that fails the memory requirement. Fixing it
will move the number, and that is the honest trade.

---

## Should fix — the response cache can serve stale answers

`cache.py` keys on `(model, normalized question text)` with **no conversation
context**. Their docstring is admirably honest about this, so it is a known
tradeoff rather than an oversight. But it interacts badly with the memory test:

```
"My name is Hanzlah"  ...  "What is my name?"  -> "Hanzlah"   (cached)
"My name is Ali"      ...  "What is my name?"  -> "Hanzlah"   (stale replay)
```

Verified the keys collide: same question, different casing, identical hash.
The cache also persists to disk across sessions, so a stale answer survives a
restart. If the lead runs the memory test twice with different values, the
second run silently replays the first.

**Fix:** include a hash of the conversation so far in the key, or skip the
cache for turns matching recall-style phrasings.

---

## Minor

**`.env` is not loaded outside Docker.** `chat.py` reads `os.environ` directly
and there is no `python-dotenv` dependency, but the error message says *"or put
it in a .env file"* — which does not work. Either add `dotenv` or reword to
"export it".

**`requirements.txt` is unpinned** (`groq>=0.11.0`). Running against groq
0.31.1 outside Docker, every single turn failed:

```
[error handling turn: Completions.create() got an unexpected keyword
 argument 'disable_tool_validation']
```

Inside Docker it installs groq 1.6.0, which supports the flag, so the
documented path works. But an unpinned floor means a future release can break
it silently. Pin exact versions (we hit the same class of problem and pinned
everything).

Credit where due: the failure was *caught* — the REPL printed the error and
kept going rather than crashing. The never-crash guarantee held under a real
failure, which is more than most implementations manage.

**`MAX_TOOL_ROUNDS = 3` with a forced no-tools final round** is a nice touch —
guarantees a text answer rather than looping. Ours caps at 8 and raises. Theirs
is arguably better UX.

---

## Things they did better than us

- **CI builds the Docker image.** Ours only runs tests, so a broken Dockerfile
  would reach main. Worth copying.
- **`--mode simple` / `--mode optimized` as a runtime flag.** Makes the
  before/after comparison a one-line change for a reviewer; ours needs editing
  `cli.py`. Better for demonstrating the cost work.
- **Forced final round** after N tool rounds, instead of erroring out.
- **Cheaper per turn**, with the memory caveat above.

## Things we did that they might want

- SSRF guard on `fetch_url` (must-fix 1)
- Explicit exponent cap in the calculator — theirs is saved by Python's
  integer-conversion limit rather than an intentional guard, which happens to
  work but is not load-bearing
- Pinned dependencies
- History rollback on a failed turn, so a partial tool-call cannot corrupt
  later requests
- Per-tool result caps (measured −16%; a single global cap measured *worse*
  than no cap at all)

---

## Summary for the PR

Two must-fix: **SSRF in `fetch_url`** (demonstrated leaking a local file), and
**memory recall failing in the default mode** (the thing the lead said he would
test). Both are small changes.

Everything else is solid, the cost work is real and genuinely beats ours, and
the error handling held up under a failure I did not plan for.
