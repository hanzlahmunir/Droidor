# Q5 FINAL FIX — Multi-Query Expansion + Inference Prompt

**Question:** How does Gatsby die?

## Step 1 — Multi-query expansion (LLM rephrases into diverse queries)

- Who shot Jay Gatsby in the swimming pool
- Gatsby's death by gunshot wound at his Long Island mansion
- What led to the fatal confrontation between Gatsby and George Wilson
- The role of Daisy Buchanan's husband in Gatsby's tragic demise
- How a bullet from George Wilson's gun ended Gatsby's life in West Egg

## Step 2 — Unioned retrieval across all queries

- Death-scene markers now in retrieved context: **[]**
- Retrieved chunks:
  1. `A dim background started to take shape behind him, but at her next
remark it faded away....`
  2. `It was Gatsby’s father, a solemn old man, very helpless and dismayed,
bundled up in a long...`
  3. `heightened sensitivity to the promises of life, as if he were related
to one of those intr...`
  4. `------------------------------------------------------------------------

At two o’clock G...`
  5. `It was a random shot, and yet the reporter’s instinct was right.
Gatsby’s notoriety, sprea...`
  6. `James Gatz—that was really, or at least legally, his name. He had
changed it at the age of...`

## Step 3 — Final answer

- Answered: **False**

> The provided context does not answer this question.


## Verdict — a valuable NEGATIVE result

Multi-query expansion **did not** retrieve the death scene, and Q5 refused.
This is important and non-obvious. Here is exactly why, proven by a controlled
retrieval comparison (no LLM):

| Query | Death chunk in top-6? |
|---|---|
| Day-2 probe: "Gatsby shot dead in the pool, **mattress, Wilson body, blood, holocaust**" | ✅ rank 1 |
| LLM sub-query: "Who shot Jay Gatsby in the swimming pool" | ❌ not found |
| Union of ALL 5 fluent LLM sub-queries | ❌ not found |

**The mechanism:** The Day-2 probe query worked because it contained the *rare,
distinctive nouns that literally appear in Fitzgerald's prose* — "mattress,"
"holocaust," "Wilson's body." The LLM's sub-queries, asked to "rephrase the
question," produced **fluent, natural language** — "Who shot Jay Gatsby in the
swimming pool" — which reads well to a human but shares almost no rare
vocabulary with the oblique source text (which never says "shot Gatsby" or
"swimming pool murder"). Fluent ≠ retrievable.

**The deepest retrieval lesson of the project:**
> Query expansion helps ONLY if it injects the SOURCE's rare vocabulary, not
> topically-related fluent language. An LLM asked to rephrase writes *clear*
> queries — but clarity is the opposite of what embedding-matching against
> idiosyncratic literary prose needs. It needs the weird specific words
> ("mattress," "holocaust"), which a keyword-EXTRACTION prompt would surface but
> a rephrasing prompt does not.

**Why the agent (Exp 7) still succeeded where this failed:** the agent did not
rephrase once and stop — it searched, saw the miss, and tried progressively
different queries including the bare surname "Wilson" and "George Wilson shot
Gatsby," iterating until something hit. Iteration + varied vocabulary beats a
single batch of fluent rephrasings. Retrieval on hard, oblique text is a
*search* problem, and the agent searches; one-shot expansion does not.

**To actually fix Q5 via passive retrieval** would require either (a) a
keyword-extraction expansion that emits rare source nouns, or (b) larger
`parent` context so the death chunk rides along with a retrievable neighbor.
The agentic approach remains the most robust general solution.