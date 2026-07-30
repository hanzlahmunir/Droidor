# Cost analysis

Measured on a fixed 10-turn transcript (`benchmark.py`), replayed identically
against every configuration. Model: `openai/gpt-oss-120b`
($0.15/$0.60 per Mtok), with `openai/gpt-oss-20b` ($0.075/$0.30) as the cheap
tier for routing.

> **These are modelled costs, not bills.** Groq's free tier bills $0. Every
> figure here is computed locally from the token counts the API returns,
> priced at published paid rates (verified against groq.com/pricing on
> 2026-07-29). That is what the exercise asks for, but it is not billing data
> and is not presented as such.

---

## Headline

| | cost/turn | vs baseline |
|---|---|---|
| **Before** — full history, no optimisations | **$0.000275** | — |
| **After** — per-tool caps + cheap-model routing | **$0.000218** | **−21%** |

Both figures are from runs with the same API call count (see *Why call count
matters* below). Memory recall stayed 3/3 in every measured configuration.

**This is not the 50% the brief asked for.** The ceiling analysis at the end
explains why 50% is not reachable on this workload with these levers, and what
would be needed to get there.

---

## Where the cost actually is

From the baseline run:

```
input   21,959 tokens   $0.003294   82% of cost
output   1,170 tokens   $0.000702   18% of cost
```

Input dominates because the API is stateless: the entire conversation is
resent on every turn. Input grew **8.3×** from turn 0 (324 tokens) to turn 9
(2,684 tokens), so cumulative session cost is O(n²).

That shape dictates everything below. Shortening replies — the instinctive
move — optimises the 18%.

---

## Why call count matters (the measurement trap)

Across 20 ten-turn runs, the correlation between **API call count** and cost
per turn is **0.739**.

Call count is decided by the model: how many times it chooses to search, and
whether it re-fetches a page. That varies run to run on *identical* input and
independently of configuration. It swamps the effects being measured.

```
13 calls  n=9   mean $0.000269
15 calls  n=2   mean $0.000341
17 calls  n=3   mean $0.000326
19 calls  n=1   mean $0.000387
```

Averaging a config's runs against baseline's runs therefore compares *search
luck*, not configuration. Every number in this document is from runs with
matching call counts. `compare.py --repeats N` prints that grouping.

**This mistake was made and corrected during the work.** An early single-run
measurement reported truncation at −16%; the aggregate across all runs later
showed −1%. Neither was right: −16% was one lucky run, −1% averaged across
different call counts. The matched comparison gives −16% at equal call count,
which is the real effect.

---

## Per-change attribution

### A — Per-tool result caps

Tool results are not paid for once. A result enters history on the turn it is
fetched and is **resent on every subsequent turn**. One `web_search` result
(2,472 chars) plus one `fetch_url` result (4,662 chars) inflated turn 4 to
4,722 input tokens and kept turns 5–6 above 2,400.

Capping what a tool result contributes to history:

| | input tokens | cost/turn |
|---|---|---|
| baseline (13 calls) | ~13,700 | $0.000275 |
| with caps (13 calls) | 11,491 | **$0.000230** |

**−16%**, recall 3/3.

**A single global cap made things worse.** At 800 chars for everything,
truncating a 4,662-char `fetch_url` result removed what the model needed, so
it re-fetched three more pages — turn 4 went from 2 API calls to 6, and cost
rose to $0.000312, *above* baseline. The caps are now per tool:

```python
"web_search": 1600   # 5 results; dropping the tail loses whole results
"fetch_url":  3000   # the model reasons over this in depth
                     # calculator (~20 chars) is never truncated
```

The lesson generalises: truncating below what the current turn needs does not
save money, it relocates the cost into retries.

### B — Fact-preserving history summary

Compress older turns into one summary block; keep recent turns verbatim.

**Measured as a net loss on a 10-turn session:**

```
overhead   ~$0.000229 per summarisation call
saving     ~153 input tokens/turn thereafter  ~= $0.000023/turn
=> break-even ~10 further turns per summarisation
```

At the original 1,500-token trigger it fired 3 times in 10 turns, turning a
16% win into a 68% loss. The saving accrues per remaining turn while the cost
is paid up front, so firing early and often is exactly backwards.

The trigger is now 6,000 tokens, so short sessions never summarise and long
ones do it rarely. **The revised threshold is not yet measured** — the free
tier's 200k daily token limit was exhausted during benchmarking. It is kept in
the codebase, off by default, with the economics documented.

Two bugs found here, both worth noting because neither would fail a unit test:

- `max_tokens=400` silently truncated a summary mid-line at `- Preference:` —
  exactly where the user's stated preferences would have been — destroying a
  fact the recall test then failed on. Now 1,200, and a summary that still
  hits the cap is discarded rather than used.
- The summariser rewrites history directly, bypassing the append path, so the
  summary never reached the transcript. A recall failure would have been
  undiagnosable because the very text the model reasoned from was missing from
  the log. Now explicitly recorded.

### C — Cheap-model routing

Route turns needing no tool and no deep reasoning to `gpt-oss-20b` (2× cheaper
on both sides). The decision is free — string and length heuristics only.
Calling an LLM to classify difficulty would spend a call to save a call.

7 of 10 turns route cheap; all three tool turns correctly stay on the capable
model.

| | cost/turn |
|---|---|
| baseline (14 calls) | $0.000281 |
| caps + routing (14 calls, n=2) | **$0.000218** |

**−22%**, recall 3/3.

---

## Why 50% is not reachable here

**Routing has a hard ceiling of 30%.** 59% of tokens are on cheap-routable
turns, and the cheap model is exactly 2× cheaper: `0.59 × 50% = 30%`. The
other 41% of tokens are on tool turns that must stay on the capable model.

**The cheapest available model is unusable.** `llama-3.1-8b-instant` is
3× cheaper on input and 7.5× on output, which would raise the ceiling
substantially. Measured on the recall turns the router would send it:

```
llama-3.1-8b-instant   recall 2/6   tool-generation errors 1
openai/gpt-oss-20b     recall 6/6   tool-generation errors 0
```

2/6 recall fails the requirement the lead explicitly set. Rejected.

**Summarisation cannot close the gap at this length**, per the break-even
maths above.

So the realistic ceiling is roughly caps (16%) + routing (22%) ≈ 30–35%
combined, not 50%.

**What would reach 50%:**

- **A longer session.** Every lever here scales with session length — the
  O(n²) input growth is what they attack, and 10 turns barely enters the
  quadratic region. Summarisation alone turns positive somewhere past ~20
  turns.
- **Prompt caching — correction.** An earlier version of this document said
  Groq offered caching only on `kimi-k2`. **That was wrong.** It is available
  on `gpt-oss-120b` and `gpt-oss-20b` — the models used here — automatically,
  with no code change, at 50% off cached input.

  It is still **not claimed as a lever**, because we could not measure its
  effect: the `usage.prompt_tokens_details.cached_tokens` field the docs
  describe is not exposed on this account, so the cost impact cannot be
  quantified. Latency probing found a clear bimodal cache signal at ~2,700
  tokens (11ms hit vs 146ms miss, 40% hit rate) but no usable signal at the
  sizes most of our turns actually run at. Full investigation, including the
  control run that overturned a false positive: [CACHING.md](CACHING.md).

  Switching to `kimi-k2` to get *explicit* cached pricing was considered and
  rejected on arithmetic: at $1.00/$3.00 per Mtok against gpt-oss-120b's
  $0.15/$0.60, it costs **3.6× more even with a 100% cache hit rate**. A 50%
  discount cannot close a 6.7× base-rate gap.
- **A capable-but-cheap small model.** The 30% routing ceiling is set by the
  2× price gap. A model at 5× cheaper that still passes recall would move it
  to ~47%.

---

## Reproducing

```bash
docker compose run --rm benchmark          # one 10-turn run, default config
python compare.py --repeats 3              # all configs, matched comparison
```

Raw per-call records: `logs/cost_log.jsonl` (one row per API call, with
`turn_index` and `call_index` so multi-call turns stay attributable).
