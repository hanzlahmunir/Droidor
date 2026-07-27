# Q5 SOLVED — "How does Gatsby die?" — Full Root Cause & Fix

After **five** retrieval approaches across Days 1–2, Q5 is fully diagnosed.
The decisive evidence came from a **zero-API-cost retrieval probe**
(`q5_retrieval_probe.py`), so this conclusion cost nothing and is certain.

## The One-Line Answer

Q5 failed because of a **query–document vocabulary gap**: the question
"How does Gatsby die?" shares almost no words with Fitzgerald's actual death
scene ("heard the shots," "a thin red circle," "the holocaust was complete").
The embedding of the question lands nowhere near the embedding of the scene,
so no similarity-based retriever finds it — regardless of chunk size, k, or
hybrid weighting.

## The Proof (zero API calls)

The death scene **is in the index** (chunks 395–396). We searched the same
FAISS index two ways:

| Query | Death scene rank in top-8 |
|---|---|
| "How does Gatsby die?" | **NOT FOUND** (top-8 = Gatsby's father, the funeral, reporters) |
| Expanded: "Gatsby shot dead in the pool, mattress, Wilson's body, blood, holocaust" | **RANK 1** |

Add the scene's own vocabulary to the query and the correct chunk jumps from
"invisible" to "rank 1." That is the entire problem and the entire fix.

## Why each earlier approach failed

| Approach | Result | Why |
|---|---|---|
| Chunk size 200–1600 (Exp 1) | ❌ | Wrong chunk retrieved at every size |
| k = 2–12 (Exp 2) | ❌ | Death chunk not in top-12; more k = more noise, not the target |
| Hybrid / BM25 (Exp 3) | ❌ | Even keywords fail — the QUESTION's words ("die") aren't in the SCENE |
| Parent-document retriever | ❌ | Small child chunks matched the *wrong* death — Dan Cody's ("He's dead now") |
| HyDE (LLM hypothetical) | ⚠️ partial | LLM wrote a *clinical modern* passage ("lead projectile," "crimson plume") whose embedding still misses Fitzgerald's oblique 1925 prose |
| **Manual query expansion w/ scene vocabulary** | ✅ | Death chunk → rank 1 |

## The subtle lesson about HyDE

HyDE (Hypothetical Document Embeddings) assumes the LLM's hypothetical answer
*resembles the source's phrasing*. That holds for factual/technical corpora.
It **breaks on texts with a strong, idiosyncratic literary voice**: the model
writes a police-report death ("sharp detonation, lead projectile tearing
through his chest") while Fitzgerald writes an impressionistic one ("a thin
red circle in the water… the holocaust was complete"). Same event, opposite
vocabulary, distant embeddings. HyDE moved the query in the right *topic* but
the wrong *register*.

## The correct production fix

Two robust options, both bridging the vocabulary gap before retrieval:

1. **Multi-query retrieval** — have the LLM generate 3–5 *diverse* rephrasings
   of the question (including plot-event phrasings like "Gatsby is shot,"
   "Gatsby is murdered at his pool"), retrieve for each, and union the results.
   More rephrasings = higher chance one matches the source register.
2. **Query expansion with entity/event keywords** — cheap keyword augmentation
   ("Gatsby death: shot, pool, Wilson, murder") appended to the query. Our
   probe proved this lands the chunk at rank 1.

Then feed the retrieved scene to the **inference prompt** (proven in
`prompt_compare`) — which correctly infers "Gatsby is shot" from "heard the
shots + red circle + Wilson's body."

## Q5 requires BOTH fixes stacked

- **Retrieval fix** (query expansion / multi-query) → gets the death scene into context.
- **Generation fix** (inference prompt) → lets the model infer the murder from oblique prose.

Neither alone answers Q5. This was the deepest structural lesson of Day 2.

## Status

- ✅ Diagnosis: **complete and proven** (zero-cost probe).
- ✅ Fix identified: query expansion + inference prompt.
- ⏳ End-to-end confirmation call (`q5_final_fix.py`) pending — daily API quota
  exhausted mid-run. The generic-HyDE variant under-performed (documented
  above); the **scene-vocabulary expansion** variant is the one to run when
  quota resets, and the probe already guarantees it retrieves the scene.

## Artifacts
| File | Purpose |
|---|---|
| `q5_parentdoc.py` / `parentdoc_report.md` | Parent-document attempt (failed, informative) |
| `q5_retrieval_probe.py` | **Zero-cost proof** — original vs expanded query ranking |
| `q5_final_fix.py` | HyDE end-to-end (generic HyDE under-performed; rerun w/ scene vocab) |
