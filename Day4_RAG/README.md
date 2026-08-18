# Day 4 — RAG over the Day 3 corpus

Answers questions from the **112 articles** crawled on Day 3. Every answer
cites the articles it came from. Questions the corpus does not cover get
**"I don't know"** rather than a guess — and that refusal is measured, not
hoped for.

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

The corpus is 112 articles in Day 3's Postgres volume. If you do not have it,
create it by running Day 3 once:

```bash
cd ../Day3_Crawler
docker compose up -d
docker compose --profile cli run --rm crawler seed --per-feed 35

cd ../Day4_RAG
docker compose up -d
docker compose --profile cli run --rm rag ingest
```

`--per-feed 35` is what produced the 112-article corpus these numbers were
measured on. `seed` makes live requests to other people's servers, so it takes
15-25 minutes at the default politeness settings, and the exact article count
will differ as those blogs publish.

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

**The balance between them shifted as the corpus grew, and that is the most
interesting result here.**

At 20 articles the floor caught 7 of 8 unanswerable questions — it was doing
most of the work. At 112 articles it catches about half, because the hard
cases now look exactly like genuine answers to a cosine score. Six questions
in the eval set are *near-misses* by construction: plausible questions about
real, densely-covered articles whose specific fact is simply absent.

| near-miss question | best chunk | would cite |
| --- | ---: | --- |
| What accuracy did SymptomAI achieve on its benchmark? | **0.702** | SymptomAI |
| How much does Cloudflare charge per million Workers requests? | 0.601 | Workers AI control plane |
| What is the parameter count behind SymptomAI? | 0.571 | SymptomAI |
| Which Django version is recommended for production? | 0.569 | Django article |
| What SQLite page size does the author recommend? | 0.505 | SQLite article |
| How do I set up OAuth2 device flow in Rust? | 0.498 | The Agent Access Model |

Genuine answers live in that same 0.5–0.7 band, so **no floor separates
them.** All six were tested end to end and all six were refused — by the
prompt, not the threshold:

```text
Q: What accuracy did SymptomAI achieve on its benchmark?
   best chunk: 0.702  (floor is 0.425 — comfortably passes layer 1)
A: I don't know.
   (The model judged the retrieved sources insufficient.)
```

So the floor's job is not what it was. It is now a **cheap pre-filter** that
kills obvious nonsense (quicksort, Formula One) before a token is spent, while
the prompt carries the hard cases. A threshold-only system at this corpus size
would fabricate answers to 46% of the unanswerable set; a prompt-only system
would pay for an LLM call on every one of them and have no measurable refusal
behaviour at all.

**The argument for two layers gets stronger with scale, not weaker.**

Citations are **validated, not trusted**: any `[n]` pointing outside the
sources actually sent is stripped. A fabricated citation is worse than none,
because it looks like provenance while being invented.

### The known limitation: a URL is not a claim

One question in 43 produces an intermittent hallucination — **1 run in 10** at
temperature 0.1:

```text
Q: Which Django version does the author recommend for production?
A: The author points to the Django 6.0 documentation (e.g. the performance
   and models topics are linked to /docs.djangoproject.com/en/6.0/),
   indicating they recommend using Django 6.0 in production [3][6].
```

`6.0` appears in that article **only as a path segment inside documentation
links** — `docs.djangoproject.com/en/6.0/topics/performance/`. The author never
recommends a version.

This is the most dangerous shape a RAG failure can take, because every
safeguard reported success: retrieval found the right articles, the score
cleared the floor (0.569), and the citations were *valid* — `[3]` and `[6]`
point at real chunks that really were sent. Only reading the source text
catches it. Retrieval metrics score this question as fine.

A prompt rule was added for it ("only prose states facts; a link target is not
a claim the author made") and **measured not to work**: 1 in 10 before, 1 in 10
after, 10 trials each, with the rule verified present in the prompt. It is kept
because it is correct and free, but it is documentation rather than a fix.

The honest conclusion: **the prompt layer is a probabilistic filter, not a
guarantee.** It catches near-miss questions reliably (6/6, including one
scoring 0.702) but cannot be relied on for a specific failure mode, because
"obey this instruction every time" is not something a sampled model does. A
deterministic fix belongs in code — stripping URLs from chunk text before the
model sees them — which has its own cost, since sometimes a link *is* the
answer. Not done here, and named rather than hidden.

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

(Measured on the 20-article corpus. At 112 articles the same setting yields
2183 chunks with 1.6% truncated — the ratio improved, so 700 still holds.)

The residual 2.7% is not fixable by shrinking further: it is code blocks kept
whole on purpose, plus link-dense prose (URLs tokenise at ~1.6 chars/token
against prose's ~3.9). `ingest` reports the count rather than hiding it.

### `SIMILARITY_FLOOR` — 0.35 → 0.40 → 0.425, and what that taught

The first tuning was done on a **20-article** corpus and gave 0.40: 100%
recall, 87.5% refusal. It looked excellent. It did not survive contact with a
real corpus.

Re-running **the same 23 questions** against 112 articles, with no code change
at all:

| @ floor 0.40 | 20 articles | 112 articles |
| --- | ---: | ---: |
| recall | 100% | 100% |
| refusal | 87.5% | **62.5%** |
| false-answer | 12.5% | **37.5%** |

The false-answer rate tripled because more text means more accidental matches.
The clearest single case: *"What were the main causes of the 2008 financial
crisis?"* scored **0.24** at 20 articles and **0.404** at 112, where it clears
the floor and would cite a *Cloudflare DDoS Threat Report* — matched purely on
vocabulary overlap ("crisis", "causes", "attacks soar").

**A threshold tuned on a small corpus does not transfer.** That is the single
most useful thing this project measured.

The eval set was then rewritten to 30 answerable + 13 unanswerable, weighted
toward questions that only become possible once topics collide. At the current
settings:

| floor | recall | refusal | false-answer |
| ----: | -----: | ------: | -----------: |
| 0.400 | 100.0% | 46.2% | 53.8% |
| **0.425** | **100.0%** | **53.8%** | **46.2%** |
| 0.500 | 90.0% | 61.5% | 38.5% |
| 0.575 | 73.3% | 84.6% | 15.4% |

0.425 is the highest floor that keeps 100% recall. Going higher buys refusal
by refusing *real* questions — 0.575 rejects the Steve Yegge quote (0.512) and
the MiniMax hardware question (0.554). The sweep's own "best balanced" column
prefers 0.575, and it is wrong to: that metric weighs a missed answer exactly
as heavily as a fabricated one.

**Both rates are reported because either alone is meaningless.** A floor of
-1 scores 100% recall while answering everything wrongly; a floor of 1.0
scores 100% refusal while being useless. The test suite asserts exactly this.

### `TOP_K` — 5 → 12

At 20 articles this value was irrelevant. At 112 it is not:

| top_k | recall | refusal |
| ----: | -----: | ------: |
| 5 | 96.7% | 53.8% |
| 8 | 96.7% | 53.8% |
| **12** | **100.0%** | **53.8%** |
| 16 / 20 | 100.0% | 53.8% (identical — saturated) |

*"What is the Cloudflare CI SDK built on top of?"* retrieves four Cloudflare
**marketing** posts scoring 0.575–0.613 ahead of the article that answers it
at 0.568 — 25 Cloudflare articles share so much boilerplate that the embedding
barely separates them. Raising `top_k` costs nothing in refusal, because these
false positives score high rather than ranking low.

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
| `TOP_K` | 12 | Chunks the search returns. Measured — see above. |
| `SIMILARITY_FLOOR` | 0.425 | The refusal gate. Measured — see above. |
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

### The index was silently returning the wrong answer

The one worth reading. Chroma indexes vectors with **HNSW**, a navigable
graph: a query *walks* the graph toward the target instead of comparing
against every vector. That is what keeps vector search fast at millions of
vectors, and it means the result is **approximate** — the walk can terminate
in a local minimum while a better match sits elsewhere, unvisited.

Nothing reports this. You get plausible neighbours with plausible scores.

Found by re-running the eval and getting a different answer:

```text
"Why did the author find Playwright unsatisfying for frontend tests?"

  exact cosine over all 2195 chunks : 0.447   Testing Vue components
  what the index returned           : 0.394   a different article entirely

  six consecutive runs: 0.447 / 0.394 / 0.447 / 0.394 / 0.447 / 0.394
```

Stable *within* one process, different *between* process starts. And the true
score (0.447) sits **0.022 above** the floor (0.425) — so a graph-traversal
accident decided whether that question was answered or refused.

**The fix:** `hnsw:search_ef` 10 → 200 and `hnsw:construction_ef` 100 → 400,
set at collection creation (Chroma refuses to change index parameters on an
existing collection, so this needs `ingest --reset`). `search_ef` is how many
candidates the walk keeps in play; at the default of 10 the beam is far too
narrow for a 2195-node graph. At this scale the cost is single-digit
milliseconds.

**Verify it yourself:**

```bash
docker compose run --rm rag eval --check-index
# -> Checked 43 questions against exact cosine similarity.
#    The index returned the true nearest chunk every time.
```

That command brute-forces exact cosine over the whole collection and reports
every question where the index disagrees. It is deliberately O(n) — precisely
what an index exists to avoid — so it is a diagnostic, not part of the query
path. Before the fix it reported 2 of 43 questions with a sub-optimal top-1,
worst gap 0.172.

**The general lesson:** a vector database returns approximate results by
default, and an eval measured through a mis-tuned index is not reproducible.
Checking against brute force is cheap at this corpus size and is the only way
to know.

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
