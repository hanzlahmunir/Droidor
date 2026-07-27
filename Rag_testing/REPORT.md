# RAG Testbed — Build Report

A living report, updated as the project is built. It records what exists, the key
decisions behind it, how to set up and run it, and verification results per phase.

## What this is

A **RAG configuration testbed**: a Streamlit app to run a single query through
*multiple* independently-configured RAG pipelines **at once** and compare their
answers and speed side-by-side. Built to empirically evaluate which RAG setup
(LLM × effort × framework × data store) works best — the natural next step after
the 3-day RAG study in `../Rag_init`.

Each **config window** exposes:

- **LLM** — provider + model, driven by whichever API keys are present
- **Effort** — a number (1–10) that scales retrieval depth and (where supported) model reasoning effort
- **Framework** — LangChain vs LangGraph (a 3rd is a future add)
- **Store** — Chroma (vector) vs Neo4j (graph)

## Key decisions

| Area | Choice | Why |
|------|--------|-----|
| Frontend | Streamlit | Pure Python, one process, no separate server/CORS — standard for ML tooling |
| Dataset | Amazon Reviews 2023 (`raw_meta_Video_Games`) | Open, structured e-commerce; rich metadata for both vector + graph |
| LLM access | LangChain `init_chat_model` + per-provider adapters | One unified interface for Anthropic/OpenAI/Gemini; provider list is **key-driven** |
| Embeddings | Local `sentence-transformers` (free) | Ingestion never blocked on an embedding API key |
| Vector store | Chroma (embedded, + SQLite) | Local, zero-config |
| Graph store | Neo4j Community (Docker) | Free; showcases graph retrieval over product relationships |
| Effort semantics | 1–10 → retrieval `k` + rewrite/rerank toggles + native `reasoning_effort` | Single knob, concrete behavior |

### Provider note: Groq (confirmed)
The user's available key is **Groq** (fast LPU inference, `langchain-groq`) — the same
provider as the prior study (`../Rag_init`); the earlier "grok" was a spelling slip for
Groq, not xAI's Grok. Both are wired anyway (xAI is one extra key-driven adapter), so if
an `XAI_API_KEY` appears later it lights up too. Live end-to-end LLM testing uses Groq;
the user adds `GROQ_API_KEY` to `.env` at test time.

## Setup

See [README.md](README.md). Short version: `pip install -r requirements.txt`,
copy `.env.example` → `.env` and add one LLM key, `python ingest.py --limit 2000
--stores chroma`, then `streamlit run app.py`.

## Build progress — COMPLETE

- [x] **Phase 0 — Repo init**: git repo, `.gitignore`, seed `REPORT.md`, private GitHub repo `rag-testbed`, first commit + push.
- [x] **Phase 1 — Scaffold**: folders, `requirements.txt`, `.env.example`, `docker-compose.yml`, `config.py`.
- [x] **Phase 2 — LLM registry**: key-driven providers + `get_llm`.
- [x] **Phase 3 — Ingestion**: `ingest.py` (Chroma verified; Neo4j path written).
- [x] **Phase 4 — Stores**: `chroma_store.py` (verified), `neo4j_store.py`.
- [x] **Phase 5 — Frameworks**: `langchain_rag.py`, `langgraph_rag.py`.
- [x] **Phase 6 — Runner + metrics**.
- [x] **Phase 7 — Streamlit UI**.
- [x] **Phase 8 — README**.

## Verification log

- **Config**: `effort_to_settings(5)` → k=7, rewrite on, grade off, medium reasoning. ✓
- **Registry (key-driven)**: no keys → `[]`; add `XAI_API_KEY` → `['xai']`; add another → both, in catalog order. ✓
- **Ingestion**: `ingest.py --limit 300 --stores chroma` indexed 300 products; similarity search for "board game for kids" / "puzzle for adults" returned relevant, correctly-categorized products. ✓
- **Chroma store**: `retrieve()` and `as_retriever()` both return relevant docs via the `Store` interface. ✓
- **Frameworks (fake LLM over real Chroma)**: effort=2 → `retrieve→generate` (k=4); effort=8 → `rewrite→retrieve→grade→generate` (k=10). Step traces confirm the conditional graph shape. ✓
- **Runner**: missing-key configs return clean per-config `error` (not crashes); `run_all` preserves order and isolates failures. ✓
- **Streamlit (AppTest)**: script renders with no exception; **+ Add window** goes 1→2 windows (4→8 selectboxes); **Run All** with placeholder keys shows 2 inline errors without crashing. App also serves live (HTTP 200, health `ok`). ✓

## Live LLM verification (Groq)

Ran with a real `GROQ_API_KEY` (`llama-3.1-8b-instant`):

- **Direct + parallel runner**: multiple configs (LangChain/LangGraph × effort 2/8) over
  the real Chroma store returned grounded answers citing actual catalog products, with real
  latencies and token counts. Effort visibly changed the pipeline (effort=8 added
  rewrite + grading). ✓
- **Full UI path (AppTest, real key)**: 2 windows (LangChain + LangGraph, low effort),
  Run All → **0 errors, both succeeded, "⏱ Time" metrics rendered (0.61s / 0.47s)**. ✓

Two bugs found and fixed during live testing:

1. **Chroma thread race** — concurrent first-time client construction under the runner's
   thread pool raced on the SQLite tenant ("Could not connect to tenant default_tenant").
   Fixed with a lock + single shared client in `stores/chroma_store.py`.
2. **dotenv inline-comment bug** — `XAI_API_KEY=   # comment` was parsed with the comment
   *as the value*, so xAI wrongly appeared configured and got selected. Fixed by moving
   comments to their own lines in `.env.example` and hardening `available_providers()` /
   `get_llm` to ignore blank or `#`-prefixed values (`_has_key`).

Note: Groq **free tier** caps ~6000 tokens/min, so firing many high-effort windows at once
can 429 (handled gracefully as a per-window error). True per-call speed is ~0.4–0.6s.

## Remaining / handoff

- **Neo4j path**: `neo4j_store.py` + `ingest.py --stores neo4j` are written but not yet
  run against a live Neo4j (`docker compose up -d` required).
- **3rd framework** ("Hermes"): deferred per the user; adapter slot ready in `frameworks/`.
- Model IDs in `config.py` may drift (providers rotate names); update if any 404s.
