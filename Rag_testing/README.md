# RAG Testbed

Compare RAG pipelines side-by-side. Add multiple **config windows**, each an
independent pipeline (LLM × effort × framework × data store), type one query,
and run it through all of them **in parallel** — each window shows its answer
and how long it took, so you can judge quality *and* speed at a glance.

![what it does](#) <!-- add a screenshot here after first run -->

## Features

- ➕ **Add/remove config windows** dynamically
- **Key-driven LLM providers** — only providers whose API key is in `.env` appear
  (Anthropic, OpenAI, Gemini, xAI/Grok, Groq)
- **Effort knob (1–10)** that scales retrieval depth + reasoning (see below)
- **Frameworks:** LangChain (LCEL) vs LangGraph (agentic StateGraph)
- **Stores:** Chroma (vector) vs Neo4j (graph, with relationship-aware retrieval)
- **Per-window metrics:** latency, tokens, estimated cost, sources, pipeline trace
- **Parallel runs** with per-window error isolation (one broken config never blocks the rest)

## Setup

```bash
# 1. Install deps  (Python 3.11–3.14 supported)
pip install -r requirements.txt

# 2. Configure keys
cp .env.example .env         # then edit .env and add at least one LLM key
                             # e.g. GROQ_API_KEY=gsk_...

# 3. Ingest data into Chroma  (downloads a dataset shard on first run)
python ingest.py --limit 2000 --stores chroma

# 4. Run the app
streamlit run app.py
```

Open the URL Streamlit prints, add a window or two, type a query, and hit **Run All**.

### Optional: Neo4j (graph store)

```bash
docker compose up -d                       # starts Neo4j on :7474 / :7687
python ingest.py --limit 2000 --stores neo4j
```

Then pick **neo4j** as the store in any window.

## How "effort" maps to behavior

The effort slider (1–10) is the single knob that trades speed for thoroughness:

| Effort | Retrieved `k` | Query rewrite | Doc grading + retry | Native reasoning |
|:------:|:-------------:|:-------------:|:-------------------:|:----------------:|
| 1–3    | 3–5           | off           | off                 | low              |
| 4–5    | 6–7           | on            | off                 | medium           |
| 6–7    | 8–9           | on            | on (≤2 rounds)      | medium           |
| 8–10   | 10–12         | on            | on (≤3 rounds)      | high             |

- **Query rewrite** turns the question into a keyword-rich search query (helps when
  fluent questions miss the catalog's vocabulary).
- **Doc grading** (LangGraph) checks whether retrieved products are relevant and, if
  not, reformulates and retries retrieval before answering.
- **Native reasoning** is passed to models that support it (e.g. Grok `reasoning_effort`,
  OpenAI o-series); others ignore it.

The exact mapping lives in [`config.py`](config.py) → `effort_to_settings`.

## Architecture

```
app.py (Streamlit)
  └─ rag_runner.py       config -> pipeline, parallel run_all, error isolation
       ├─ frameworks/    langchain_rag.py | langgraph_rag.py   (base.py interface)
       ├─ stores/        chroma_store.py  | neo4j_store.py      (base.py interface)
       ├─ llms/registry  key-driven providers via init_chat_model / ChatXAI / ChatGroq
       └─ metrics.py     latency, tokens, cost
ingest.py                Amazon Reviews 2023 (Toys & Games) -> Chroma / Neo4j
```

Every run is fully described by a `RagConfig` (provider, model, effort, framework,
store). Each dimension is an adapter, so adding an option is a small, local change —
that's what makes this a *testbed* rather than a few hardcoded pipelines.

## Data

[Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) (McAuley Lab, UCSD),
`raw_meta_Toys_and_Games` config, loaded directly from the Hugging Face parquet
shards. Product docs are built from title + description + features; the graph store
also models `SOLD_BY`, `IN_CATEGORY`, and `ALSO_BOUGHT` relationships.

> Video Games isn't materialized as a standalone parquet folder in the HF repo (only
> 9 categories are), so Toys & Games is used as the closest available fit. To switch
> categories, change `HF_META_CONFIG` in `config.py` to any `raw_meta_*` folder that
> exists in the [dataset repo](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/tree/main).

## Notes

- **Model IDs** in `config.py`'s `MODELS` table may drift over time (providers rotate
  model names — Groq especially). If a model 404s, update the list to a current id.
- **Adding a 3rd framework** (LlamaIndex/Haystack/etc.): implement `RagFramework` in a
  new file under `frameworks/`, register it in `frameworks/base.get_framework`, and add
  its name to `FRAMEWORKS` in `config.py`.
