# RAG From Scratch — A Three-Day Empirical Study

**Corpus:** *The Great Gatsby* by F. Scott Fitzgerald (271k chars, Project Gutenberg)
**Stack:** LangChain / LangGraph · FAISS · HuggingFace embeddings · Gemini → Groq LLMs
**Goal:** understand, hands-on and empirically, how Retrieval-Augmented Generation
actually works — every layer, measured, with the failures documented as
carefully as the successes.

---

## The One-Paragraph Summary

We built RAG from a bare pipeline up to autonomous agents, measuring each layer.
The recurring lesson: **the obvious culprit is usually not the real one.** We
spent two days tuning *retrieval* when the real bottleneck was first the
*generation prompt*, then the *evaluation metric*, then the *query vocabulary*,
and finally the *API provider*. The single most capable design — an agent that
searches, sees its miss, and reformulates — autonomously re-derived nearly every
fix we had hand-engineered. And the hardest question ("How does Gatsby die?")
taught us more by staying broken across a dozen approaches than any easy win
could have.

---

## Day-by-Day Arc

### Day 1 — Build the pipeline (3 ways)
Built the same RAG three ways to learn the abstractions:
- **LangGraph** `StateGraph` agent (explicit nodes/edges, max control)
- **LCEL** pipe chain (`{context, question} | prompt | llm | parser`, concise)
- **`init_chat_model`** provider-agnostic init
Ran it on the real book; compared 3 embedding models (MiniLM / mpnet / nomic).
Takeaway: embedding choice changes *which* chunks are retrieved; MiniLM is the
fast dev default, nomic best quality/query-speed.

### Day 2 — Tune retrieval… and discover retrieval wasn't the problem
Four experiments + a root-cause hunt:
- **Chunk size** (200→1600): 800 is the sweet spot.
- **k** (2→12): gains plateau by k=8.
- **Hybrid search** (semantic/BM25/ensemble): 30/70 blend best all-rounder.
- **Root cause of the refusals:** not retrieval — the **strict prompt**. Same
  retrieval, an *inference-permitting* prompt cut refusals 3/5 → 1/5. The model
  had been refusing to make one-step inferences ("shots heard + blood + body =
  shot dead").
- **LLM-as-judge** then showed the keyword scorer had been **lying to us**
  (flagged an 83% answer as REFUSED). True picture: **zero hallucination**
  across all answers.

### Day 3 — Agents, guardrails, evaluation, ops
Seven experiments (switched Gemini → Groq for speed/quota):
- **Agentic RAG (7):** the agent autonomously reformulated queries (solved Q5)
  and decomposed multi-hop questions — re-deriving Day 2's manual fixes.
- **Multi-tool agent (8):** 4/4 correct tool routing incl. exact counting
  (verified 5 and 23) — tasks retrieval fundamentally cannot do.
- **Input guardrails (9):** LLM gate 10/10 vs embedding gate 8/10; topical
  similarity ≠ intent (no threshold separates a sparse valid question from an
  injection wearing on-topic words).
- **Output guardrails (10):** citations + groundedness check caught the
  training-data-leak trap.
- **Recall@k (6):** measured retrieval *directly* — cleanly separated retrieval
  failures (Q4/Q5, chunk never found) from generation limits (Q3, found at
  rank 1 but under-answered).
- **Ground-truth correctness (5):** found a third failure mode — *misleading*
  retrieval producing confident wrong answers ("Who killed Myrtle?" → "Tom").
- **Streaming (11):** ~6x better perceived latency. **Async (12):** a surprise
  3.7x *slowdown* from rate limits — bounded concurrency required.

---

## The Case of Q5 — "How does Gatsby die?"

One question anchors the whole study. It failed across **~15 configurations** —
4 chunk sizes, 4 k values, 4 retrieval strategies, parent-document retrieval,
generic HyDE, and multi-query expansion. Each failure taught something:

1. **Not chunk size / k / hybrid** — the death chunk is never in the top-k.
2. **Not the prompt alone** — even hand-fed the perfect passage, the *strict*
   prompt refused; the *inference* prompt answered ("shot by George Wilson").
3. **Not generic HyDE** — the LLM wrote a *clinical* death ("lead projectile,
   crimson plume"); Fitzgerald wrote an *impressionistic* one ("thin red circle
   … the holocaust was complete"). Opposite registers, distant embeddings.
4. **Not multi-query expansion** — the LLM's *fluent* rephrasings ("Who shot
   Gatsby in the pool") shared no rare vocabulary with the prose.
5. **Recall@k proved it quantitatively:** chunk 396 (the death) is unretrievable
   by any similarity method for this query — a true **query–document vocabulary
   gap**.
6. **Only the agent solved it** — by *iterating*: search → miss → reformulate
   ("Gatsby shot" → "Gatsby murdered" → "George Wilson shot Gatsby") until a
   query finally matched. Retrieval on oblique text is a **search** problem, and
   only the agent searches.

**Q5's lesson:** the answer existed the whole time; the barrier was that the
question and the text don't speak the same words. No single-shot method bridges
that reliably — iterative, agentic search does.

---

## Cross-Cutting Lessons (what "how RAG works" actually means)

1. **RAG has three independent failure surfaces** — retrieval, generation, and
   *evaluation* — and a failure in any one masquerades as a failure in another.
   Diagnosis means isolating them (force-feed context to test generation;
   Recall@k to test retrieval; read raw outputs to test the scorer).

2. **The generation prompt is a tunable dial, not a fixed rule.** Too loose →
   hallucination; too strict → refusal-on-inference. Aim: "reason FROM the
   context, don't import facts BEYOND it."

3. **Your metric shapes your conclusion.** Keyword scoring said "3/5 fail";
   LLM-judge said "0 hallucinations, retrieval is the limiter." Same answers,
   opposite stories. Always sanity-check surprising scores against raw text.

4. **Failure modes are plural and ranked by danger:**
   retrieval-finds-nothing (refuses — safe) <
   retrieval-finds-partial (incomplete) <
   retrieval-finds-*misleading* (confident + WRONG — most dangerous).

5. **Query expansion needs the source's rare vocabulary, not fluent language.**
   Clarity is the enemy of embedding-match against idiosyncratic prose.

6. **Guardrails are layered:** cheap embedding pre-filter (catches obvious
   off-topic, free) → LLM gate (catches intent/injection) → output citation +
   groundedness (catches training-data leakage). Defense in depth.

7. **Agents replace hand-engineering with judgment.** Everything we manually
   tuned in Days 1–2 (query reformulation, decomposition, tool selection), the
   agent did on its own. This is why the field moved to agents.

8. **Infrastructure is a first-class variable.** The same code was unusable on
   Gemini's RPM limit and instant on Groq — then blocked again by Groq's daily
   token cap, and by model-specific tool-calling reliability. Provider/model
   choice is an engineering decision, not a detail.

---

## Scoreboard — Experiments Run

| # | Experiment | Day | Verdict |
|---|---|---|---|
| — | Build pipelines (LangGraph/LCEL/init) | 1 | done |
| — | Embedding model comparison | 1 | nomic best quality; MiniLM best dev speed |
| 1 | Chunk size | 2 | 800 optimal |
| 2 | k value | 2 | plateau at k=8 |
| 3 | Hybrid search | 2 | 30/70 blend best |
| 4 | LLM-as-judge | 2 | 0 hallucinations; keyword scorer was misleading |
| 5 | Ground-truth correctness | 3 | exposed "misleading retrieval" failure mode |
| 6 | Recall@k | 3 | separated retrieval vs generation failures |
| 7 | Agentic RAG | 3 | autonomously solved Q5 + multi-hop |
| 8 | Multi-tool agent | 3 | 4/4 tool routing; verified counts |
| 9 | Input guardrails | 3 | LLM gate 10/10 > embedding 8/10 |
| 10 | Output guardrails | 3 | citations + groundedness caught leak trap |
| 11 | Streaming | 3 | ~6x better perceived latency |
| 12 | Async throughput | 3 | rate limits → bounded concurrency needed |
| 13 | Local LLM (Ollama) | 3 | skipped (install required) |

**14 of 15 planned experiments completed.** Only the local-LLM comparison
remains, blocked solely on an Ollama install.

---

## Repository Map

```
day1/  — pipelines, book RAG, embedding comparison  (embedding_report.md)
day2/  — chunk/k/hybrid tuning, prompt root-cause, LLM-judge, Q5 hunt
         (DAY2_MASTER_REPORT.md + per-experiment reports)
day3/  — agents, tools, guardrails, recall, correctness, streaming, async
         (DAY3_MASTER_REPORT.md + per-experiment reports)
FINAL_REPORT.md  — this document
```

Each experiment has a runnable script and a standalone report. All indexes and
answers are disk-cached, so reports regenerate without recomputation.
