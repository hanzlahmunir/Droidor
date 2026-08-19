# RAG evaluation baseline

Run `docker compose run --rm eval` (or `python eval.py`). Everything below is
the output of that command plus what it means. This is the number the rest of
the week gets compared against. How to run it is in [README.md](README.md).

```
Questions:         20
Top-1 correct:     14/16  (88%)
Top-5 correct:     15/16  (94%)
Answer correct:    12/16  (75%)
Refused correctly:  4/4
```

Recorded 2026-08-18 against 113 articles / 2195 chunks; `CHUNK_SIZE=700`,
`TOP_K=12`, `SIMILARITY_FLOOR=0.425`, answers from `openai/gpt-oss-120b`.
Full per-question detail in `data/reports/day5_baseline.json`.

The corpus reads **112** articles from 2026-08-19 onward — article 113 was
dropped by a Day 3 re-crawl. The index is unchanged at 2195 chunks and no
question referenced that article, so the numbers above still reproduce; see
the drift section below for why this is now checked automatically rather than
noticed by luck.

## Reading the denominators

Top-1, Top-5 and Answer correct are scored over the **16 answerable**
questions. The 4 unanswerable ones have no correct article, so counting them
as retrieval failures would mean rewarding retrieval for finding nothing.
They are scored only by the last line.

Ranking is over **articles, not chunks**. The retriever returns 12 chunks and
several are routinely from the same article; ranking them raw would make
"top-5" nearly free. Chunks collapse to their article, best chunk wins, and
the article ranking is what is scored.

Ranking also happens **before the similarity floor**. The floor is a refusal
policy, not a retrieval result. Measured together, "the search missed it" and
"the search found it and the floor discarded it" produce the same symptom and
have opposite fixes.

## The 20 questions

Written by hand from 10 articles I read: 1, 2, 3, 23, 25, 26, 29, 33, 67, 111.
7 single, 6 multi, 4 unanswerable, 3 vague — the mix the task specifies.

No LLM wrote any of them, and the reason is measurable rather than stylistic.
A model writing a question from an article reuses that article's vocabulary,
so the question's embedding lands beside the passage's almost by construction.
The retriever then scores well because the question was derived from the
answer. Questions here are deliberately worded away from the source: Q4 asks
why output "disappears" without using the word *buffering*, which is in the
title.

## What the numbers say

**Retrieval is strong and is no longer the bottleneck.** 14/16 top-1. Both
misses are the same failure and both are in the terminal cluster — 8 articles
by one author on adjacent topics, in one voice:

| Q | wanted | got | best |
|---|--------|-----|------|
| 6 — "how do I tell which shell I'm running?" | 29 | 32, 29, 31, 30 | 0.440 |
| 13 — Helix + fish | 25 | 26, 30, 31 | 0.445 |

Q6 lands on *"Rules" that terminal programs follow* instead of the PATH
article; Q13 lands on the zine announcement instead of the Helix post. Both
score ~0.44, barely over the 0.425 floor — the retriever is not confident and
is right not to be. This is the score-compression problem Day 4 flagged,
reproduced on a second cluster: within a tight topic the embeddings do not
separate, and no threshold fixes that. A reranker or a larger embedding model
would.

**Answering is the weaker half, and the gap is the finding.** 14 top-1 vs 12
answered correctly: twice, the right article was ranked first and the answer
still did not carry the required fact.

- **Q9** (multi) retrieved article 2 at 0.782 — the highest score in the set —
  and answered that the author found SQLite "complicated", which is in the
  article's opening. It never reached `ANALYZE`, the actual operational
  problem. Right article, wrong part of it. Retrieval cannot fix this; the
  fact was in the context window and went unused.
- **Q12** (multi) omitted "ANSI". On the previous run this same question died
  differently — the model spent its entire 800-token budget on hidden
  reasoning and returned nothing (`ANSWER_MAX_TOKENS=800`, a Day 4 default
  this run leaves alone).

**Refusal works, but only the second layer is doing it.** 4/4 — and all four
were caught by the *prompt*, not the floor. Every uncovered question scored
0.441–0.638, comfortably above 0.425. The deterministic gate that Day 4 built
the refusal story around fired zero times here.

That is the opposite of reassuring. Day 4 already measured that the prompt
layer is probabilistic (one hallucination in ~10% of runs on a Django version
question). 4/4 today is a good roll of a die that will not always land this
way, and lowering the floor to catch these would start refusing real
questions, which score in the same 0.44–0.6 band. Both layers cannot be tuned
by one number.

**Lazy phrasing costs nothing here.** All 3 vague questions — `sqlite analyze
slow query django` — went top-1 and answered correctly. Q18 targets the same
article as Q1 and scores *higher* (0.668 vs 0.592). Keyword soup happens to
suit embedding search, because stripped of grammar what is left is exactly the
content words. Worth not over-reading from three questions.

## Run-to-run variance, measured

Three runs, same corpus, same config, no code change between them:

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| Top-1 | 14/16 | 14/16 | 14/16 |
| Top-5 | 15/16 | 15/16 | 15/16 |
| Answer correct | 12/16 | **11/16** | **11/16** |
| Refused correctly | 4/4 | 4/4 | 4/4 |

Run 3 was taken from the standalone `Day5_Eval` stack after the split, against
the 112-article corpus. Retrieval and refusal are identical across all three;
only the answer line moves.

Run 3's extra miss versus run 1 is **Q2**, where the answer did not carry
`5 second`. Run 2's five-line output was captured but not its per-question
detail, so I cannot say whether it lost the same question — only that the line
moved by one in both cases. Worth recording precisely because the useful
version of this table is "which question flipped", and I did not keep enough
to answer that. Later runs use `--json-out`.

**A change that shifts "Answer correct" by 1 has not been shown to do
anything** — that is inside the noise. Retrieval changes of 1 are real. The
baseline at the top is run 1; all three are recorded because a baseline
without its noise floor invites reading meaning into drift.

## Three ground-truth bugs this caught, in my own eval set

The first run printed `Refused correctly: 1/4` and I nearly wrote it up as a
hallucination finding. All three "failures" were my errors:

| I claimed the corpus was silent on | It actually says |
|---|---|
| the site's hosting cost | article 1: "a ~$10/month VM" |
| DDoS attack *source* countries | article 67 has a "Top attack source countries" section — Brazil, 14.9% |
| a recommended rater minimum | article 111: "often need more than 10 raters per item" |

The system answered all three correctly and my ground truth marked each a
fabrication. I had read the articles and still got it wrong, because I was
recalling them rather than checking. The replacements are facts I grepped for
and confirmed absent.

A fourth was pure scoring: `must_contain: "5 second"` failed against the
model's `5‑second` (U+2011 non-breaking hyphen), and `"8KB"` against `8 KB`.
Correct answers, scored wrong over typography. `eval.py` now folds dashes and
whitespace before matching.

Both classes of bug fail *quietly* — they print a plausible low number, not an
error. That is why the scoring is unit-tested (`tests/test_eval_script.py`,
33 tests) rather than trusted.

## The corpus drifted the next day, which is why there is now a guard

`expect_article_ids` are database ids. The day after the baseline was
recorded, the corpus went from 113 articles to 112 — article 113 (`<antirez>`)
was gone, the Day 3 crawler having been re-run at some point.

No question referenced it and all 10 ids used here still map to their expected
titles, so **the baseline above stands unchanged**. But that is luck. Had the
ids renumbered instead, nothing would have errored: every question would still
have been scored, against the wrong articles, and the report would have
printed a confident number that meant nothing.

So each question now records the titles it expects, and every run verifies
them against the live API before scoring. On a mismatch it refuses to print a
score and names the question. Same for an empty index, which would otherwise
score 0/16 — indistinguishable from a broken retriever.

**The guard shipped with a bug of exactly the kind it exists to prevent.** The
first implementation flattened every question's expected titles into one dict
keyed by article id. Article 2 is referenced by both Q1 and Q9, so Q9's
correct entry silently overwrote Q1's — and when I corrupted Q1's title to
test the guard, it reported "no drift" and scored anyway. A guard against
silent wrong numbers, failing silently and wrongly. Found by deliberately
corrupting an entry and checking the failure actually happened rather than
assuming it did; now a regression test.

## Known limits of this baseline

- **16 answerable questions is a small denominator.** One question is 6
  percentage points. Day 4's lesson was that a score on 20 articles measures
  nothing; the corpus is fixed now, but the question set is small and the same
  caution applies to reading single-point moves.
- **`must_contain` is substring matching**, not semantic. It is checking a
  fact is *present*, not that the answer is *good* — an answer could contain
  "ANALYZE" inside a wrong explanation and score correct. Chosen deliberately:
  an LLM judge would drift between runs and make today's number
  incomparable with tomorrow's, which defeats the purpose.
- **Q13 is typed `multi` but has one expected article.** The fish comparison
  that makes it multi-hop in intent lives in the same post. The type describes
  the question; scoring uses the ids.
- **The 4 unanswerable questions are all near-misses** — plausible questions
  on covered topics. There is no "what is the capital of France" in the set,
  because the floor catches those trivially and it would inflate the refusal
  line.

## Reproducing

```bash
cd Day4_RAG
docker compose up -d                                    # db + Day 1 API
docker compose --profile cli build rag                  # or the change isn't in the image
docker compose --profile cli run --rm --entrypoint python rag eval.py --verbose

# retrieval only: no API key, no LLM calls, seconds not minutes
docker compose --profile cli run --rm --entrypoint python rag eval.py --no-llm

docker compose --profile cli build tests && docker compose --profile cli run --rm tests
```

133 tests, fully offline: Day 5's 33 plus Day 4's 100.
