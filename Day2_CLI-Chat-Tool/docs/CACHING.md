# Prompt caching on Groq — what we tried to measure, and what we actually learned

This investigation started from a wrong premise of mine, produced one clear
negative result, one inconclusive result, and one methodological lesson. Written
up honestly because the process is the point.

---

## Correction: caching IS available on our models

I previously told the user Groq offered prompt caching only on `kimi-k2`, and
`docs/COST.md` listed "no prompt caching" as the reason 50% was unreachable.
**That was wrong.** Per Groq's docs, prompt caching is available on:

- `openai/gpt-oss-120b`  ← the model we use
- `openai/gpt-oss-20b`   ← our cheap tier
- `openai/gpt-oss-safeguard-20b`

It is **automatic**: no `cache_control` parameter, no code change, no extra
fee. 50% discount on cached input tokens, 2-hour expiry, minimum cacheable
prefix 128–1024 tokens depending on model.

I had read the Kimi K2 pricing row (which lists an explicit "cached input"
rate) and concluded the others lacked it, without checking the caching docs.

---

## Why switching to Kimi K2 for caching would be a mistake

The user's suggestion was to move to `kimi-k2`, which advertises cached-input
pricing. The arithmetic rules it out, on our own 10-turn baseline
(21,959 input / 1,170 output tokens):

| Configuration | session cost | per turn | vs gpt-oss-120b |
|---|---|---|---|
| gpt-oss-120b, no caching | $0.003996 | $0.000400 | — |
| kimi-k2, no caching | $0.025469 | $0.002547 | 6.4× worse |
| kimi-k2, **100% cached input** | $0.014489 | $0.001449 | **3.6× worse** |

Kimi K2 is $1.00/$3.00 per Mtok against gpt-oss-120b's $0.15/$0.60 — 6.7× more
on input, 5× on output. A 50% discount on one component cannot close a 5–6.7×
gap on everything. Even a *perfect* cache hit rate leaves it 3.6× more
expensive than doing nothing on the cheaper model.

**Generalisable lesson: a discount percentage is meaningless without the base
rate.** "50% off" on a model that costs 6.7× more is a 3.4× price increase.

---

## Measuring cache hits: the billing field is not exposed

Groq's docs say cache hits appear as
`usage.prompt_tokens_details.cached_tokens`. On this account they do not:

```
usage keys = ['completion_time', 'completion_tokens',
              'completion_tokens_details', 'prompt_time',
              'prompt_tokens', 'queue_time', 'total_time', 'total_tokens']
prompt_tokens_details: None
```

Absent from both the typed SDK model and the raw HTTP JSON, across every call
made. So **we cannot measure the cost effect of caching directly** — the field
that would prove it isn't there. Possibly account-tier or rollout dependent.

That left `prompt_time` (prompt-processing latency) as an indirect proxy: a
cache hit should skip recomputation and be measurably faster.

---

## What `prompt_time` showed

### Result 1 — a clear bimodal signal at ~2,700 tokens

15 identical calls with a 2,691-token prefix:

```
147 311 135 54 9 158 15 13 131 136 9 718 40 146 10   (ms)

fast (<50ms):  6/15   median  11ms
slow (>=50ms): 9/15   median 146ms
hit rate:      40%
```

Sharply bimodal — ~11ms or ~146ms, a **13× difference**, with nothing in
between. Consistent with a cache that either hits or misses. Note the hit rate
is only 40%: caching here is **best-effort, not guaranteed**.

### Result 2 — the control that invalidated my first conclusion

A growing-conversation simulation (~500–620 tokens/turn) gave 8/8 "hits" at
22–32ms, and I initially read that as caching working perfectly on our real
workload shape.

Then I ran the control — same sizes, but a fresh UUID in every system prompt,
so a cache hit is *impossible*:

```
turn 0: 513 tok  26ms      turn 4: 599 tok  31ms
turn 1: 533 tok  39ms      turn 5: 618 tok  29ms
turn 2: 555 tok  93ms      turn 6: 638 tok  97ms
turn 3: 576 tok  25ms      turn 7: 658 tok  40ms
```

Equally fast. **At ~600 tokens, `prompt_time` is dominated by something other
than caching**, so the 8/8 proved nothing. Without the control I would have
reported a false positive.

### Result 3 — no signal at ~6,000 tokens

Six identical 6,084-token calls: 419, 304, 265, 261, 305, 257ms. No bimodal
drop, no hits. The opposite of the 2,691-token result.

The daily token quota (200k) was exhausted before the matching control could
run, so this one is **inconclusive** — a real absence of caching and a
`prompt_time` proxy that stops working at larger sizes look identical here.

---

## Conclusion

**Established:**
- Caching is available on the models we already use, automatically. The
  earlier claim to the contrary was wrong and `docs/COST.md` is corrected.
- Switching to Kimi K2 for caching would cost 3.6× more even at a perfect hit
  rate. Rejected on arithmetic.
- The `cached_tokens` billing field is not exposed on this account, so the
  cost effect cannot be measured directly.
- At ~2,700 tokens, repeated prefixes show a bimodal 11ms/146ms split at a 40%
  hit rate — the clearest evidence caching engages at all.

**Not established:**
- Whether caching measurably reduces *cost* on our workload. Without
  `cached_tokens`, latency is the only proxy, and the control shows it is
  unreliable below ~1k tokens and gave no signal at 6k.
- Our benchmark turns run 324–2,684 input tokens, i.e. mostly at or below the
  size where the proxy proved untrustworthy.

**So caching is not claimed as a lever in `docs/COST.md`.** It plausibly
provides some benefit we are already receiving for free, but this
investigation could not quantify it, and an unquantified effect does not go in
a results table.

---

## The methodological lesson

The control run is the whole story. "8/8 cache hits" was a satisfying result
that matched the hypothesis, and it was wrong — the fast times had nothing to
do with caching. Adding one control (same shape, cache made impossible)
converted a false positive into a real finding about the measurement itself.

This is the second time in this project that a control changed the conclusion:
the first was discovering that API call count correlates 0.739 with cost,
which meant single-run comparisons had been measuring the model's search
whims rather than any configuration change.

**A measurement you cannot invalidate is not a measurement.**
