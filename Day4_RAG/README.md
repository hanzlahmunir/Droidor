# Day 4 — RAG over the Day 3 corpus

Answers questions from the articles crawled on Day 3. Every answer cites the
articles it came from. Questions the corpus does not cover get **"I don't
know"** rather than a guess — and that refusal is measured, not hoped for.

No LangChain, no LlamaIndex. The retrieval loop is written by hand in
[app/retriever.py](app/retriever.py) — embed the question, search, convert
distance to similarity, apply the floor.

## Run it

```bash
docker compose up -d                 # db + Day 1 API + UI on :8501
docker compose run --rm rag ingest   # corpus -> chunks -> vectors
```

Then open <http://localhost:8501>, or ask from the command line:

```bash
docker compose run --rm rag ask "What did running ANALYZE do to the slow SQLite query?"
docker compose run --rm rag eval          # measured retrieval quality
docker compose run --rm rag stats         # what is indexed
docker compose run --rm tests             # 99 offline tests
```

> **First run needs Day 3's corpus.** See [Requirements](#requirements)
> immediately below — on a machine that has never run Day 3, `up` fails with
> `external volume "day3_crawler_pgdata" not found`. That is deliberate (an
> empty database would be a worse failure), and the fix is one command.

### Reviewing without having run Day 3

The corpus is 20 articles in Day 3's Postgres volume. If you do not have it,
create it by running Day 3 once:

```bash
cd ../Day3_Crawler
docker compose up -d
docker compose --profile cli run --rm crawler seed   # crawls the 5 default feeds

cd ../Day4_RAG
docker compose up -d
docker compose --profile cli run --rm rag ingest
```

Note that `seed` makes live requests to other people's servers, so it takes a
couple of minutes and the exact article count can differ from the 20 these
numbers were measured on.

To review **only this project's code** without any corpus, the test suite is
fully self-contained and needs no database, no network and no API key:

```bash
docker compose --profile cli run --rm tests    # 99 tests
```

Ingestion is deliberately **not** started by `up`: it reads the whole corpus
and computes embeddings for it, which is a real cost and should be an
explicit act.

> **Rebuild after editing source.** `docker compose run` reuses an existing
> image. Run `docker compose --profile cli build` first, or your change
> silently will not be in the container. This cost time again on Day 4 — the
> tell was `No module named app.cli` on a file that plainly existed.

### Requirements

- **Day 3 must have run.** The corpus lives in Day 3's Postgres volume
  (`day3_crawler_pgdata`), which this project attaches to as an external
  volume rather than copying. One corpus, one source of truth.
- **`GROQ_API_KEY` in `.env`** to generate answers. Retrieval works without
  it — `ask --no-llm` shows what was found.

## What it does

```text
ARTICLE ─► chunk (structure-aware) ─► embed (local) ─► Chroma

QUESTION ─► embed ─► top-k search ─► similarity floor
                                      │
                          below ──────┴────── above
                            │                   │
                      "I don't know"      LLM answers from
                     (no LLM called)      those chunks only
                                                │
                                     abstains ──┴── answers
                                          │           │
                                   "I don't know"   validate
                                                    citations
```

## The two-layer refusal

This is the part worth reviewing.

**Layer 1 — the similarity floor.** If the best chunk scores below
`SIMILARITY_FLOOR`, the answer is "I don't know" and *no LLM call is made*.
Deterministic, free, and untalkable-around: a threshold is a rule, whereas a
prompt instruction is a request.

**Layer 2 — the prompt.** Chunks can clear the floor by sharing a *topic* with
the question while not containing the answer. The prompt requires the model to
abstain in that case.

Both are needed, and one question in the eval set proves it:

```text
Q: How much does Cloudflare charge per million Workers requests?
   best chunk: 0.543  (floor is 0.40 — so it passes layer 1)
A: I don't know.
   (The model judged the retrieved sources insufficient.)
```

The corpus has five Cloudflare articles, so pricing-shaped questions match
strongly without containing the answer. No floor catches this *and* keeps full
recall — 0.55 would, at the cost of two answerable questions. A
threshold-only system would have fabricated a price from adjacent prose; a
prompt-only system would spend tokens on every unanswerable question and have
no measurable refusal behaviour at all.

Citations are **validated, not trusted**: any `[n]` pointing outside the
sources actually sent is stripped. A fabricated citation is worse than none,
because it looks like provenance while being invented.

## Measured, not guessed

Two numbers in this project were originally guesses. Both were wrong, and both
were caught by measuring instead of assuming.

### `CHUNK_SIZE` — 1000 → 700

The embedding model truncates at **256 tokens** and discards everything past
that silently — no error, just an unsearchable tail. Sweeping chunk size
against the model's own tokenizer over the real corpus:

| chars | chunks | truncated |
| ----: | -----: | --------: |
| 500 | 556 | 1.1% |
| 600 | 475 | 1.5% |
| **700** | **412** | **2.7%** |
| 800 | 352 | 5.1% |
| 1000 | 301 | 12.6% |

The residual 2.7% is not fixable by shrinking further: it is code blocks kept
whole on purpose, plus link-dense prose (URLs tokenise at ~1.6 chars/token
against prose's ~3.9). `ingest` reports the count rather than hiding it.

### `SIMILARITY_FLOOR` — 0.35 → 0.40

`rag eval` sweeps the floor over 15 answerable and 8 unanswerable questions:

| floor | recall | refusal | false-answer |
| ----: | -----: | ------: | -----------: |
| 0.350 | 100.0% | 75.0% | 25.0% |
| 0.375 | 100.0% | 87.5% | 12.5% |
| **0.400** | **100.0%** | **87.5%** | **12.5%** |
| 0.450 | 86.7% | 87.5% | 12.5% |
| 0.550 | 86.7% | 100.0% | 0.0% |

0.35 was leaving refusals on the table for free. 0.40 sits in the middle of
the 0.375–0.425 plateau rather than at its edge, so a slightly different
corpus does not tip it off a cliff.

**Both rates are reported because either alone is meaningless.** A floor of
-1 scores 100% recall while answering everything wrongly; a floor of 1.0
scores 100% refusal while being useless. The test suite asserts exactly this.

Full report: [data/reports/EVAL.md](data/reports/EVAL.md), regenerable with
`rag eval --report`.

## Configuration

Everything that affects retrieval is an environment variable — the task
requires chunk size and top-k to be config, and the rest follows for the same
reason: a tuning run that needs a code edit between trials is a tuning run
nobody does.

| Setting | Default | What it does |
| --- | ---: | --- |
| `CHUNK_SIZE` | 700 | Target chars per chunk. Measured — see above. |
| `CHUNK_OVERLAP` | 150 | Chars repeated between adjacent chunks. |
| `MIN_CHUNK_CHARS` | 80 | Below this a chunk is dropped as noise. |
| `TOP_K` | 5 | Chunks the search returns. |
| `SIMILARITY_FLOOR` | 0.40 | The refusal gate. Measured — see above. |
| `MAX_CONTEXT_CHARS` | 8000 | Bounds what is sent to the model. |
| `EMBEDDING_MODEL` | all-MiniLM-L6-v2 | Local, 384-dim, no API key. |
| `ANSWER_MODEL` | openai/gpt-oss-120b | Via Groq. |

Config **validates** rather than trusting: `CHUNK_OVERLAP >= CHUNK_SIZE` would
make chunking unable to advance and loop forever mid-ingest, so it is rejected
at startup with both numbers named.

## Design decisions worth defending

**Chroma, not pgvector.** Days 1–3 established Postgres with Alembic
migrations, and Day 4 breaks that: Chroma persists to a directory, so this
project has **no schema under version control**. That is the real cost of the
choice and it is the first thing a reviewer coming from Day 3 should notice.
What it buys is no extension, no migration, and a store reduced to `add` and
`query` so the retrieval logic stays visible and the store stays swappable.

**Embeddings computed by us, not by Chroma.** Chroma's `embedding_function` is
deliberately left unset. It would happily pick a model, embed the query, and
decide what matches — which is exactly the part the task exists to make you
write.

**The corpus is read over HTTP, not from the table.** Day 4 could connect to
the same Postgres directly. Going through `GET /documents` keeps one
definition of "a document" — the same reasoning Day 3 used when it POSTed
instead of INSERTing.

**Chunks carry their heading.** Each chunk is embedded with its section
heading prefixed. "It returns None if the key is missing" is nearly
meaningless alone; under `## dict.get()` it embeds close to a question about
`dict.get`. 85% of chunks carry one. This matters more to retrieval quality
than any threshold tuning.

**Citation metadata is denormalised onto every chunk.** A citation must be
renderable from the chunk alone — no join, no second API call — and must
survive the article later being deleted from Day 1.

## Bugs only a live run found

Consistent with Day 3, the bugs that mattered were invisible to a green test
suite.

**1. Overlap was corrupting code blocks.** The overlap tail was a blind
character slice of the previous chunk. Where that chunk ended with code, the
tail was a fragment of the block *plus its closing fence* — so the next chunk
began mid-function with an orphaned ` ``` `. **12 chunks** in the real corpus
looked like this while every unit test passed, because the test prose was
short enough that the tail never landed inside a fence. Overlap is now
line-based and stops at a fence. 12 → 0.

**2. The answer model does not emit `[1]`.** It emits `【1†L1-L4】` and `【1】` —
CJK brackets, mixed freely with ASCII in one answer, despite the prompt asking
otherwise. The validator dropped all of them, so correct, well-sourced answers
displayed *"No valid citations — treat this answer with suspicion."* The
failure was in the safe direction, but it made citations useless on most
answers. The *stripping* path had the same bug: `text.replace("[7]", "")`
cannot see an invented `【7†L1-L4】`.

**3. `openai/gpt-oss-120b` is a reasoning model.** It spends completion tokens
on a hidden `reasoning` field before writing `content`. At `max_tokens=100` it
returned `finish_reason='length'` with **content empty** — which would render
as a blank answer. Measured: a RAG answer needs ~275 tokens. Empty content now
raises a diagnosable error naming `ANSWER_MAX_TOKENS`.

## Tests

```bash
docker compose run --rm tests    # 99 tests, fully offline
```

No network, no database, no API key, no model download. Retrieval is exercised
against a **real Chroma collection** in a temp directory using a fake
embedder — Chroma is the dependency whose behaviour is relied on, so mocking
it would test the mock. The embeddings are faked because their *semantics* are
measured by `rag eval` against the real corpus, not asserted in unit tests.

## Layout

```text
app/
  config.py      every tunable, env-driven, validated
  corpus.py      loads articles from the Day 1 API (paginated)
  chunker.py     structure-aware Markdown splitting  (pure functions)
  embedder.py    the only module that loads the model
  storage.py     the Chroma boundary; distance -> similarity in ONE place
  retriever.py   the retrieval loop and the refusal gate
  answerer.py    prompt, generation, citation validation
  evaluate.py    the floor sweep
  cli.py         ingest / ask / eval / stats
  ui.py          Streamlit
data/
  eval_questions.json    15 answerable + 8 unanswerable, verified by hand
  reports/EVAL.md        generated evidence for the chosen floor
```
