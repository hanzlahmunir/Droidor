# Day 3 · Experiment 11 — Streaming vs Non-Streaming

**Question:** Describe the relationship between Gatsby and Daisy in detail.

## Latency

| Mode | Time to first visible token | Time to full answer |
|---|---|---|
| Non-streaming | 3.68s (blank until done) | 3.68s |
| Streaming | **0.58s** | 2.96s |

- **Perceived-latency improvement: 6.3x** — the user starts reading at 0.58s instead of 3.68s.
- Streaming delivered the answer in 1224 incremental chunks.
- **Total time is ~the same**; streaming wins purely on UX — the user is never staring at a blank screen.

## Takeaway

- For any user-facing RAG app, stream. Total compute is identical, but time-to-first-token is what users actually feel. A 2-3s wait for a full answer feels slow; the same answer streaming from ~0.3s feels instant.

## Sample answer
> **Gatsby ↔ Daisy – a relationship built on illusion, longing, and the impossible**

The passage you supplied gives us a highly‑charged, almost theatrical snapshot of the bond between Jay Gatsby and Daisy Buchanan. Though it is not a verbatim excerpt from Fitzgerald’s novel, the language and the emotional beats echo the original dynamics and amplify them with a more explicit, almost confessional tone. Below is a detailed breakdown of what the text tells us about their relationship, organized arou
