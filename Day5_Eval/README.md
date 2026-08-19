# Day 5 — Measure your RAG

One command that prints a score, so tomorrow's changes get compared against
today instead of guessed at.

```
$ docker compose run --rm eval

Questions:         20
Top-1 correct:     14/16  (88%)
Top-5 correct:     15/16  (94%)
Answer correct:    12/16  (75%)
Refused correctly:  4/4
```

The baseline and what it means are in **[RESULTS.md](RESULTS.md)**. This file
is how to run it.

---

## Quickstart

Day 5 measures the Day 4 system, so Day 4 must have ingested at least once.

```bash
# 1. Day 4 builds the index (once, or after any config change)
cd ../Day4_RAG
docker compose up -d
docker compose run --rm rag ingest --reset

# 2. Day 5 scores it
cd ../Day5_Eval
cp .env.example .env          # then paste your GROQ_API_KEY
docker compose run --rm eval
```

That is the whole demo. `run`, not `up`: this is a measurement that runs and
exits, so there is no service to leave running.

| Command | What it does |
|---|---|
| `docker compose run --rm eval` | The five lines. |
| `docker compose run --rm eval --verbose` | Plus a per-question table with scores and failure reasons. |
| `docker compose run --rm eval --no-llm` | Retrieval only. No API key, no LLM calls, seconds instead of minutes. |
| `docker compose run --rm eval --json-out data/reports/x.json` | Full per-question detail to disk. |
| `docker compose run --rm tests` | 133 tests, fully offline — no network, no key, no database. |

It also runs without Docker if the deps are installed: `python eval.py`.

---

## What the five numbers mean

**Top-1 / Top-5 — retrieval.** Was the right article the first hit, and was it
in the first five.

Two decisions here change what these numbers mean, and both are deliberate:

- **Ranking is over articles, not chunks.** The retriever returns 12 chunks
  and several are routinely from the same article. Ranking them raw would
  make "top-5" nearly free — one article's chunks would fill every slot.
  Chunks collapse to their article, best chunk wins.
- **Ranking happens *before* the similarity floor.** The floor is a refusal
  policy, not a retrieval result. Measured together, "the search missed it"
  and "the search found it and the floor discarded it" produce the same
  symptom and have opposite fixes.

**Answer correct** — every `must_contain` token appears in the generated
answer. Substring, case-insensitive, with typography folded (see below).

**Refused correctly** — of the 4 uncovered questions, how many said "I don't
know". Either layer counts: the similarity floor (before any LLM call) or the
model abstaining. `--verbose` shows which one fired, which matters, because
right now it is always the second.

**The denominators are 16 and 4, not 20.** The 4 unanswerable questions have
no correct article, so scoring them for retrieval would reward the retriever
for finding nothing. They are scored only by the last line.

---

## The 20 questions

In [eval_set.json](eval_set.json). Hand-written from 10 articles I read:
ids 1, 2, 3, 23, 25, 26, 29, 33, 67, 111. Seven `single`, six `multi`, four
`unanswerable`, three `vague`.

**None were LLM-generated, and the reason is measurable rather than
stylistic.** A model writing a question from an article reuses that article's
vocabulary, so the question's embedding lands beside the passage's almost by
construction. Retrieval then scores well because the question was derived from
the answer. Questions here are deliberately worded *away* from the source —
Q4 asks why pipe output "disappears" without using the word *buffering*, which
is in the title of the article that answers it.

One entry:

```json
{
  "id": 1,
  "question": "Which command fixed the slow full-text search query, and how much faster did it get?",
  "expect_article_ids": [2],
  "must_contain": ["ANALYZE", "0.05"],
  "type": "single",
  "_titles": { "2": "Learning a few things about running SQLite" }
}
```

`must_contain` accepts a nested list as OR — `[["beginning", "front"]]` passes
on either — so a correct answer is not punished for word choice.

`_titles` is the drift guard, below.

---

## Two guards, because a wrong score does not look like an error

Both of these exist because of bugs that actually happened here. Neither
crashed. Both printed a plausible number that was wrong, which is the failure
mode worth engineering against.

**An empty index refuses to score.** If nothing is ingested, every question
scores zero — indistinguishable from a broken retriever. `eval.py` stops and
names the command to run instead.

**A drifted corpus refuses to score.** `expect_article_ids` are database ids,
and they are ground truth only while they point at the articles they pointed
at when the questions were written. Re-crawl and they renumber; nothing
errors, and every question is scored against the wrong article. So each
question records the titles it expects, and the run checks them against the
live API:

```
The corpus has drifted since these questions were written, so
expect_article_ids no longer identify the right articles and any
score printed now would be measured against wrong ground truth:
  - id 2 is now 'Learning a few things about running SQLite', but Q1 expects 'A Totally Different Article'

Re-verify eval_set.json before trusting a number. To score anyway
(the result is not comparable to RESULTS.md), pass --skip-corpus-check.
```

This is not hypothetical: article 113 disappeared from the corpus between the
baseline run and the next day. No question referenced it, so the baseline
stands — but that is luck, and luck is what the guard replaces.

---

## Layout, and why Day 5 does not copy Day 4

```
Day5_Eval/
  eval.py            the scorer
  eval_set.json      20 hand-written questions + expected titles
  RESULTS.md         the committed baseline
  Dockerfile         FROM the Day 4 image
  docker-compose.yml builds ../Day1_Documents-API and ../Day4_RAG from source
  tests/             33 tests for the scoring itself
  data/reports/      --json-out lands here
```

`Dockerfile` is `FROM` the Day 4 image and `docker-compose.yml` builds it from
`../Day4_RAG`. Nothing is vendored.

The retriever, embedder, config and answerer under measurement are the *real*
ones at their current revision. A copy would drift the moment Day 4 changed,
and a score describing a stale copy of the retriever is worse than no score —
because it looks valid. This is the same reasoning that has Day 3 and Day 4
build the Day 1 API from source rather than vendoring it.

The costs of that choice, stated plainly:

- **Day 5 cannot run without Day 4 present**, and needs Day 4 to have ingested.
- **Retrieval settings are duplicated** in `.env.example`. They do not
  re-chunk anything at eval time, but `TOP_K` and `SIMILARITY_FLOOR` change
  what is retrieved and refused. Change them in Day 4 and you must change them
  here, or the comparison to RESULTS.md is meaningless.
- **`docker compose run --rm tests` here runs Day 4's suite too** (100 of the
  133). That is deliberate: it proves Day 5 did not break what it measures.

Unlike Day 4, this stack does **not** publish port 8000. Both share one
database, and two published mappings means whichever starts second dies with
"port is already allocated" — a known Day 4 open item there was no reason to
duplicate. Day 5 reaches the API over the compose network.

---

## Known limits

- **16 answerable questions is a small denominator.** One question is 6
  percentage points.
- **The answer line moves by ±1 between identical runs.** Retrieval is
  deterministic and does not. A change that shifts "Answer correct" by one
  question has not been shown to do anything; see the variance table in
  RESULTS.md.
- **`must_contain` is substring matching, not semantic.** It checks a fact is
  *present*, not that the answer is *good* — an answer could contain
  "ANALYZE" inside a wrong explanation and score correct. Chosen deliberately:
  an LLM judge would drift between runs and make today's number incomparable
  with tomorrow's, which is the entire point of a baseline.
- **Typography is folded before matching** — dashes and whitespace are
  stripped from both sides. Real false negatives it fixes: `5‑second`
  (U+2011) against `5 second`, and `8 KB` against `8KB`. Correct answers were
  being scored wrong over invisible characters.
