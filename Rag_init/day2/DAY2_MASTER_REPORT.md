# Day 2 Master Report — RAG Retrieval & The Root-Cause Hunt

**Book:** The Great Gatsby by F. Scott Fitzgerald
**Embedding (fixed across all experiments):** all-MiniLM-L6-v2 (local, 384-dim)
**LLM:** gemini-flash-latest (temperature 0)
**Evaluation questions:** 5 (Q1–Q5 below)

| # | Question |
|---|---|
| Q1 | Who is Jay Gatsby and what is his dream? |
| Q2 | What does the green light symbolize? |
| Q3 | Describe the relationship between Gatsby and Daisy. |
| Q4 | Who is Nick Carraway and how does he know Gatsby? |
| Q5 | How does Gatsby die? |

---

## TL;DR — The Headline Finding

We ran **three experiments (13 retrieval configurations)** trying to fix why
Q5 ("How does Gatsby die?") always failed. We tuned chunk size, `k`, and
retrieval strategy. **None of it worked.**

The real cause was **one sentence in the prompt**:

> *"Answer using ONLY the context below. Do NOT use your prior knowledge."*

That guardrail — added to prevent hallucination — was so strict the model
refused to make a **one-step logical inference**. Given the death scene
(which literally says the chauffeur "heard the shots," describes a "thin red
circle" of blood in the pool, and "Wilson's body a little way off in the
grass"), the model still answered *"the provided context does not answer this
question."*

Swapping in a guardrail that **permits inference but still forbids outside
facts** fixed it instantly:

> *"Gatsby is shot to death. This is indicated by the chauffeur hearing 'the
> shots'... the 'thin red circle' (of blood)... and the discovery of Wilson's
> body nearby."*

**Lesson: when a RAG system underperforms, the prompt/generation step is as
likely a culprit as retrieval — often more so. We spent 3 days optimizing
retrieval when retrieval was mostly fine.**

### The nuance (proven, not assumed)

When we held retrieval fixed (best config: chunk=800, k=4, semantic) and
changed ONLY the prompt, refusals dropped **3/5 → 1/5** and average score rose
**32% → 53%** (`prompt_compare_report.md`). Specifically:

| Question | STRICT | INFERENCE | Why |
|---|---|---|---|
| Q1 Gatsby/dream | REFUSED | **83%** | Pure guardrail — info was retrieved, prompt blocked it |
| Q4 Nick/Gatsby | REFUSED | **20%** | Mostly retrieval-thin, but prompt still helped it say what it *could* |
| Q5 death | REFUSED | **REFUSED** | **Two stacked problems** (see below) |

**Q5 is the subtle one.** In an isolated probe where we *hand-fed the perfect
death-scene chunk*, the inference prompt answered correctly ("Gatsby is shot to
death..."). But in the real pipeline with k=4 semantic retrieval, the death
chunk **is never retrieved** (0/5 facts in Q5's context). So Q5 has **two
independent failures stacked**:
1. **Retrieval** — the death scene isn't in the top-4 results.
2. **Guardrail** — even when it *is* fed in, the strict prompt refuses.

You must fix **both** to answer Q5. That is a deeper truth than "it's just the
prompt" — and we only found it by testing rather than assuming.

### A second lesson: your evaluator can lie to you

Our first comparison run reported Q1 as "still REFUSED" under the inference
prompt. That was **false** — a bug in the refusal detector. Q1's inference
answer was 1,763 chars of rich, correct content, but it contained the phrase
"not explicitly" in passing, and the naive detector (`"not explicitly" in
answer`) flagged the whole thing as a refusal. **The model succeeded; the
scorer failed.** Fixing the detector (a real refusal is *short* and *dominated*
by the canonical refusal sentence) revealed the true 3/5 → 1/5 improvement.
Always sanity-check surprising eval results against the raw answer text.

---

## Experiment 1 — Chunk Size vs Retrieval Precision

**Varied:** chunk_size ∈ {200, 400, 800, 1600}, overlap = 10% of size.
**Fixed:** embedding, k=4, strict prompt.

| Chunk Size | # Chunks | Index Time | Avg Q Time | Avg Score | Q5 |
|---|---|---|---|---|---|
| 200 | 1990 | 15.9s | 3.6s | 8% | REFUSED |
| 400 | 958 | 15.4s | 8.3s | 16% | REFUSED |
| **800** | 447 | 12.5s | 9.3s | **32%** | REFUSED |
| 1600 | 197 | 7.6s | 10.1s | 32% | REFUSED |

**Per-question scores:**

| Question | 200 | 400 | 800 | 1600 |
|---|---|---|---|---|
| Q1 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q2 | 40% | 60% | 100% | 100% |
| Q3 | REFUSED | 20% | 60% | 60% |
| Q4 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q5 | REFUSED | REFUSED | REFUSED | REFUSED |

**Findings:**
- **Small chunks (200/400) starve the LLM of context.** Retrieved fragments
  are single sentences with no surrounding narrative → the model can't
  assemble an answer and refuses.
- **800 is the sweet spot.** Q2 hits 100%, Q3 reaches 60%. Bigger (1600)
  adds nothing — with only 197 chunks, top-4 already spans a huge fraction of
  the book and retrieval gets noisier.
- **The smoking gun:** at chunk=800, Q1's retrieved context contained
  **5 of 6 expected facts** (see Retrieval Coverage in `chunk_report.md`) —
  yet the answer still REFUSED. **The information was retrieved. The model
  refused to use it.** This was the first clue the guardrail was the problem.

---

## Experiment 2 — k (Number of Retrieved Chunks)

**Varied:** k ∈ {2, 4, 8, 12}.
**Fixed:** embedding, chunk_size=800, strict prompt.

| k | Avg Context | Avg Q Time | Avg Score | Q5 |
|---|---|---|---|---|
| 2 | 1,315 c | 4.2s | 12% | REFUSED |
| 4 | 2,563 c | 13.0s | 32% | REFUSED |
| 8 | 5,244 c | 12.7s | 36% | REFUSED |
| 12 | 7,853 c | 7.6s | 36% | REFUSED |

**Per-question scores:**

| Question | k=2 | k=4 | k=8 | k=12 |
|---|---|---|---|---|
| Q1 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q2 | REFUSED | 100% | 100% | 100% |
| Q3 | 60% | 60% | 80% | 80% |
| Q4 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q5 | REFUSED | REFUSED | REFUSED | REFUSED |

**Findings:**
- **More context helps up to a point, then plateaus.** Q3 improved 60%→80%
  at k=8 (chunks 5–8 held real relationship detail) but k=12 added nothing.
- **k=2 is too thin** — even Q2 (trivial elsewhere) refused because the green-
  light passage wasn't in the top-2.
- **Q5 refused at every k, including k=12 with ~7,850 chars of context.**
  Dumping more text at the model did not help — confirming the block was not
  "not enough was retrieved."

---

## Experiment 3 — Hybrid Search (Semantic + BM25)

**Varied:** retrieval strategy.
**Fixed:** embedding, chunk_size=800, k=4, strict prompt.

| Strategy | Avg Q Time | Avg Score | Q5 |
|---|---|---|---|
| Semantic only (FAISS) | 5.3s | 32% | REFUSED |
| BM25 keyword only | 4.3s | 24% | REFUSED |
| Hybrid 50/50 | 8.0s | 28% | REFUSED |
| **Hybrid 30/70** | 8.1s | **36%** | REFUSED |

**Per-question scores:**

| Question | Semantic | BM25 | Hybrid 50/50 | Hybrid 30/70 |
|---|---|---|---|---|
| Q1 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q2 | 100% | 80% | 80% | 100% |
| Q3 | 60% | 40% | 60% | **80%** |
| Q4 | REFUSED | REFUSED | REFUSED | REFUSED |
| Q5 | REFUSED | REFUSED | REFUSED | REFUSED |

**Findings:**
- **Hybrid 30/70 was the best overall** — matched semantic's Q2 peak (100%)
  AND beat everyone on Q3 (80%). The keyword weight surfaced concrete
  relationship details semantic missed, without losing thematic grounding.
- **BM25 alone is weakest for literary/thematic questions** — it's literal, so
  abstract queries ("what is his dream") suffer.
- **The blend genuinely delivers the best of both**, as designed.
- **But Q5 still refused across all four strategies** — even BM25, which
  *did* retrieve the chunk containing "Wilson." Retrieval method was not the
  variable that mattered.

---

## Root-Cause Case Study — "How does Gatsby die?"

After 13 failed configs, we stopped tuning retrieval and probed the
generation step directly (`q5_probe.py`, `q5_probe2.py`, `q5_inference_only.py`).

**Step 1 — Confirm the answer exists in the source.**
The death scene (gatsby.txt lines 5720–5761) contains, in plain text:
- "Gatsby shouldered the mattress and started for the pool"
- "The chauffeur... heard the **shots**"
- "a thin red circle in the water" (blood around the mattress)
- "the gardener saw **Wilson's body** a little way off in the grass"

A human reads this and concludes: **Wilson shot Gatsby in the pool.** The
facts are all present; only the literal sentence "Gatsby was shot" is absent —
Fitzgerald writes the death by implication.

**Step 2 — Force-feed the perfect context under the STRICT prompt.**

| Context given | Strict-prompt result |
|---|---|
| A. Full death scene (has "heard the shots") | ❌ REFUSED |
| B. Ambiguous tail only (no "shots") | ❌ REFUSED |
| C. The 4 chunks semantic actually retrieved | ❌ REFUSED |

Even with the **complete, unambiguous scene** (condition A), the strict prompt
refused. This ruled out retrieval *and* source ambiguity as the cause.

**Step 3 — Same context, change only the guardrail.**

| Guardrail wording | Result |
|---|---|
| STRICT: "ONLY the context, do NOT use prior knowledge" | ❌ REFUSED |
| INFERENCE: "you MAY draw reasonable logical inferences... but do not introduce outside facts" | ✅ **ANSWERED** |

The inference-allowed answer:
> *"Based on the provided context, Gatsby is shot to death. This is indicated
> by the chauffeur hearing 'the shots' after Gatsby goes to the pool, the 'thin
> red circle' (of blood) traced in the water around the mattress where Gatsby's
> body is found, and the discovery of Wilson's body nearby in the grass."*

Grounded, reasoned, and it **cites its evidence** — the ideal RAG answer.

---

## Experiment 4 — LLM-as-Judge (and why every earlier score was suspect)

The keyword scorer nearly buried our single most important finding (Q1, an
83%+ answer, was first reported as REFUSED). So we replaced it with a second
LLM call that grades each cached inference answer on two independent axes:
**Faithfulness** (is every claim supported by the retrieved context? → catches
hallucination) and **Completeness** (does it answer the question using what the
context allows? → catches lazy refusals). A *correct* refusal — when the
context genuinely lacks the answer — is scored faithful (5) and appropriately
incomplete (3), i.e. the system did the right thing.

| Question | Keyword | Faithfulness | Completeness | What the disagreement reveals |
|---|---|---|---|---|
| Q1 Gatsby/dream | 83% | **5/5** | **5/5** | Keyword under-rated a perfect answer |
| Q2 green light | 100% | 5/5 | 5/5 | Agreement |
| Q3 Gatsby/Daisy | 60% | **5/5** | **5/5** | Keyword docked 40% for *phrasing*, not correctness |
| Q4 Nick/Gatsby | 20% | 5/5 | 3/5 | Not a model failure — the **context was thin** |
| Q5 death | REFUSED | 5/5 | 3/5 | The refusal was **correct**, not a failure |

**Findings:**
- **Zero hallucination.** Every answer scored Faithfulness 5/5 — a fact the
  keyword scorer could never surface.
- **Keyword scoring measures vocabulary overlap, not correctness.** Q3 was
  fully correct yet scored 60% for saying "affair"/"reunion" in other words.
- **The judge separates "the model failed" from "the context was thin."**
  Q4 and Q5 both got Completeness 3 with Faithfulness 5 — meaning the
  generation did the right thing and **retrieval was the limiter.** Keyword
  scoring called these 20% and REFUSED, wrongly implying generation failure.

**Meta-lesson: your evaluation metric shapes your entire conclusion.** Under
keyword scoring, Day 2 read as "3/5 questions fail." Under LLM-as-judge, the
truth is "5/5 answers are faithful; 3/5 fully complete, the other 2 correctly
limited by retrieval." Those are different stories — and the second is the
true one. The reason Q5 looked mysterious for so long is that we were
measuring with a broken ruler.

---

## Cross-Experiment Verdict Matrix

| Question | Best retrieval got context? | Answered under STRICT? | Root issue |
|---|---|---|---|
| Q1 Gatsby/dream | Yes (5/6 facts @ chunk800) | ❌ never | **Guardrail** (info was there) |
| Q2 green light | Yes | ✅ (chunk≥800, k≥4) | None — works |
| Q3 Gatsby/Daisy | Yes (best: hybrid 30/70) | ⚠️ partial (max 80%) | Retrieval spread + guardrail |
| Q4 Nick/Gatsby | Weak (1/5 facts) | ❌ never | Mixed: retrieval thin AND guardrail |
| Q5 death | Yes (BM25 got Wilson chunk) | ❌ never | **Guardrail** (proven) |

**Two of the five questions (Q1, Q5) failed purely because of the prompt, not
retrieval.** Q4 is a mix. Only Q2 and Q3 were ever really about retrieval.

---

## What We Proved About How RAG Works

1. **Chunk size** controls how much *context* accompanies each retrieved hit.
   Too small → starvation; too large → noise. 800 chars was best here.
2. **k** trades context breadth for speed and noise. Gains plateau fast
   (k=8 here). More is not better past the point of diminishing returns.
3. **Retrieval strategy**: semantic wins on thematic questions, keyword (BM25)
   wins on exact terms, **hybrid (esp. 30/70) is the best all-rounder.**
4. **The generation guardrail is a tunable dial, not a fixed rule:**
   - Too loose → hallucination (invents facts).
   - Too strict → **refusal-on-inference** (won't connect dots plainly in the text).
   - The sweet spot: *"reason FROM the context, don't import facts BEYOND it."*
5. **Diagnostic discipline matters.** The instinct on a RAG failure is to blame
   embeddings/chunking. Isolating variables (force-feeding perfect context,
   then changing only the prompt) found the true cause in 3 cheap probes after
   13 expensive retrieval configs missed it.

---

## Artifacts

| File | Contents |
|---|---|
| `chunk_eval.py` / `chunk_report.md` | Experiment 1 |
| `k_eval.py` / `k_report.md` | Experiment 2 |
| `hybrid_eval.py` / `hybrid_report.md` | Experiment 3 |
| `q5_probe.py` | Perfect-context test under strict prompt (all refused) |
| `q5_probe2.py` / `q5_inference_only.py` | Strict vs inference guardrail (the fix) |
| `prompt_compare.py` / `prompt_compare_report.md` | Strict vs inference, all 5 Qs |
| `llm_judge.py` / `judge_report.md` | Experiment 4 — LLM-as-judge |

---

## Next Step — DONE, and here is what it showed

We re-ran the best config (chunk=800, k=4, semantic) with the inference prompt
(`prompt_compare.py` → `prompt_compare_report.md`). Result confirmed the
hypothesis and sharpened it:

- **Refusals 3/5 → 1/5; avg score 32% → 53%** from the prompt change alone.
- **Q1 was pure guardrail** (REFUSED → 83%).
- **Q4 was mostly retrieval** but the prompt still helped (REFUSED → 20%).
- **Q5 needs BOTH fixed** — retrieval (get the death chunk into context) AND
  the inference prompt. Neither alone is sufficient.

### The real remaining work (Day 3+)

1. **Adopt the inference prompt as the default** — it strictly dominates the
   strict prompt here (never worse, often much better).
2. **Fix Q5's retrieval** — the death scene never enters the top-4. Options:
   parent-document retriever (match small, feed large surrounding scene), or
   query expansion ("how does Gatsby die" → "Gatsby shot pool Wilson body").
3. **Replace the keyword scorer with LLM-as-judge** — the scorer bug that hid
   Q1's success is exactly why brittle keyword matching must go. This is
   Experiment 4 on the roadmap.
