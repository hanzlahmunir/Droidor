# Day 3 · Experiment 12 — Sequential vs Async Throughput

Answering the same batch of **6 questions** two ways.

| Mode | Total time | Per question |
|---|---|---|
| Sequential | 4.50s | 0.75s |
| Async (concurrent) | **16.88s** | 2.81s |

- **Result: async was 3.7x SLOWER (16.88s vs 4.50s)** — the OPPOSITE of the
  textbook expectation. This is a real, instructive finding, not a bug.

## Why async lost — rate limits beat concurrency

The textbook says: concurrent requests overlap network waits, so async should
win. It didn't, because **Groq's free tier enforces a per-minute request/token
limit**. Firing 6 requests simultaneously immediately tripped that limit; the
excess requests were server-side queued and retried (note the `queue_time`
field Groq returns), so the "concurrent" batch actually ran slower than the
polite sequential one — which naturally spaced calls out enough to stay under
the ceiling.

## Takeaway (corrected by the data)

- **Async concurrency only helps when the bottleneck is network latency AND you
  are below the provider's rate limit.** On a rate-limited free tier, blasting
  concurrent requests is counterproductive — you hit the limit and get queued.
- The correct production pattern is **bounded concurrency**: a semaphore capping
  in-flight requests to just under the provider's limit (e.g. 2-3 at a time),
  not unbounded `asyncio.gather` over everything at once.
- **Meta-lesson:** always measure. The expected "async is faster" was wrong for
  our actual constraints. The infrastructure (rate limits), not the code
  pattern, determined the outcome — the same theme as the Gemini→Groq switch.