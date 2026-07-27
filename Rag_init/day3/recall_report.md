# Day 3 · Experiment 6 — Retrieval Evaluation (Recall@k)

Measures retrieval DIRECTLY: does the ground-truth chunk (marked by a distinctive verbatim phrase) appear in the top-k? Zero LLM calls.

- **Recall@k** = ground-truth chunk is within top-k (1/0)
- **MRR** = 1 / rank of first ground-truth chunk

## Strategy: semantic

| Question | R@1 | R@2 | R@4 | R@8 | R@12 | MRR | First rank |
|---|---|---|---|---|---|---|---|
| What does the green light symbolize? | — | — | ✅ | ✅ | ✅ | 0.333 | 3 |
| How does Gatsby die? | — | — | — | — | — | 0 | not found |
| Describe the relationship between Gats | ✅ | ✅ | ✅ | ✅ | ✅ | 1.0 | 1 |
| Who is Nick Carraway and how does he k | — | — | — | — | — | 0 | not found |
| What is the last line of the book? | — | — | — | — | ✅ | 0.083 | 12 |
| **Average** | **1/5** | **1/5** | **2/5** | **2/5** | **3/5** | **0.283** |  |

## Strategy: bm25

| Question | R@1 | R@2 | R@4 | R@8 | R@12 | MRR | First rank |
|---|---|---|---|---|---|---|---|
| What does the green light symbolize? | — | ✅ | ✅ | ✅ | ✅ | 0.5 | 2 |
| How does Gatsby die? | — | — | — | — | — | 0 | not found |
| Describe the relationship between Gats | — | — | — | — | — | 0 | not found |
| Who is Nick Carraway and how does he k | — | — | — | — | — | 0 | not found |
| What is the last line of the book? | — | — | — | — | — | 0 | not found |
| **Average** | **0/5** | **1/5** | **1/5** | **1/5** | **1/5** | **0.1** |  |

## Strategy: hybrid

| Question | R@1 | R@2 | R@4 | R@8 | R@12 | MRR | First rank |
|---|---|---|---|---|---|---|---|
| What does the green light symbolize? | — | ✅ | ✅ | ✅ | ✅ | 0.5 | 2 |
| How does Gatsby die? | — | — | — | — | — | 0 | not found |
| Describe the relationship between Gats | — | — | — | — | — | 0.077 | 13 |
| Who is Nick Carraway and how does he k | — | — | — | — | — | 0 | not found |
| What is the last line of the book? | — | — | — | — | — | 0.043 | 23 |
| **Average** | **0/5** | **1/5** | **1/5** | **1/5** | **1/5** | **0.124** |  |

## Interpretation

- **High recall + wrong answer** = the retriever found the right chunk but GENERATION failed (prompt too strict, poor synthesis).
- **Low recall** = the RETRIEVER failed; no prompt fix can help.
- This cleanly separates the two failure modes we kept conflating in Days 1–2. Q5 ('how does Gatsby die') is the key case: if recall is low here, it confirms the vocabulary-gap diagnosis — the death chunk simply isn't retrieved by the plain query.