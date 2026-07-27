"""
Experiment 3 — Hybrid Search (Semantic + BM25 Keyword)
-------------------------------------------------------
Fixes: chunk_size=800, overlap=80, embedding=all-MiniLM-L6-v2, k=4

Tests 4 retrieval strategies:
  1. semantic_only  — FAISS cosine similarity (what we used in Exp 1 & 2)
  2. bm25_only      — keyword TF-IDF (BM25), no embeddings
  3. hybrid_50_50   — EnsembleRetriever: 50% FAISS + 50% BM25
  4. hybrid_30_70   — EnsembleRetriever: 30% FAISS + 70% BM25 (keyword-heavy)

Hypothesis: BM25 will surface the death scene ("Wilson", "shot", "pool")
that semantic search misses. Hybrid should get the best of both worlds.

Metrics:
  - Answer completeness score (same keyword-based scorer)
  - Q5 answered? (key test)
  - Query time
  - Which chunks were retrieved (top chunk preview)

Caching: FAISS index reused from Exp 1. BM25 built fresh (fast, in-memory).
         Answers pickled per strategy — resume-safe.

Report: day2/hybrid_report.md
Run:    python hybrid_eval.py
"""

import os, time, pickle, textwrap
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY  = "AQ.Ab8RN6L5WoVoHIRxxx3h4PdsTuub41-kMGg_ZKZ3tdbanzhN9A"
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH  = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR  = Path(__file__).parent / "chunk_cache"   # reuse Exp 1 FAISS
CACHE_DIR.mkdir(exist_ok=True)
ANS_DIR    = Path(__file__).parent / "hybrid_cache"
ANS_DIR.mkdir(exist_ok=True)

EMBED_MODEL   = "all-MiniLM-L6-v2"
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 80
FAISS_KEY     = "chunk800"
K             = 4

QUESTIONS = [
    "Who is Jay Gatsby and what is his dream?",
    "What does the green light symbolize?",
    "Describe the relationship between Gatsby and Daisy.",
    "Who is Nick Carraway and how does he know Gatsby?",
    "How does Gatsby die?",
]

ANSWER_FACTS = {
    "Who is Jay Gatsby and what is his dream?": [
        "platonic", "self", "dream", "daisy", "west egg", "rich"
    ],
    "What does the green light symbolize?": [
        "green", "daisy", "future", "dream", "dock"
    ],
    "Describe the relationship between Gatsby and Daisy.": [
        "love", "affair", "tom", "married", "reunion"
    ],
    "Who is Nick Carraway and how does he know Gatsby?": [
        "narrator", "neighbor", "west egg", "cousin", "bond"
    ],
    "How does Gatsby die?": [
        "wilson", "shot", "pool", "myrtle", "murder"
    ],
}

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer using ONLY the context below. "
    "If the context does not contain enough information to answer, say exactly: "
    "'The provided context does not answer this question.' "
    "Do NOT use your prior knowledge.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

# ── Book loading ───────────────────────────────────────────────────────────────
def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    start = raw.find("*** START OF THE PROJECT GUTENBERG")
    end   = raw.find("*** END OF THE PROJECT GUTENBERG")
    if start != -1: raw = raw[raw.find("\n", start) + 1:]
    if end   != -1: raw = raw[:end]
    return raw

def load_chunks(raw):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return splitter.create_documents([raw])

# ── FAISS — reuse from Exp 1 ──────────────────────────────────────────────────
def get_faiss(embed_fn, chunks):
    cache_path = CACHE_DIR / f"{FAISS_KEY}.faiss"
    meta_path  = CACHE_DIR / f"{FAISS_KEY}.meta"
    if cache_path.exists():
        t0 = time.perf_counter()
        vs = FAISS.load_local(str(cache_path), embed_fn,
                              allow_dangerous_deserialization=True)
        index_time = pickle.loads(meta_path.read_bytes())["index_time"]
        print(f"  [cache] FAISS loaded in {time.perf_counter()-t0:.1f}s "
              f"(built in {index_time:.1f}s)")
        return vs
    print(f"  [build] Embedding {len(chunks)} chunks ...")
    t0 = time.perf_counter()
    vs = FAISS.from_documents(chunks, embed_fn)
    index_time = time.perf_counter() - t0
    print(f"  [build] Done in {index_time:.1f}s")
    vs.save_local(str(cache_path))
    meta_path.write_bytes(pickle.dumps({"index_time": index_time}))
    return vs

# ── Retrievers ────────────────────────────────────────────────────────────────
def build_retrievers(chunks, faiss_vs):
    faiss_ret = faiss_vs.as_retriever(search_kwargs={"k": K})
    bm25_ret  = BM25Retriever.from_documents(chunks, k=K)
    hybrid_50 = EnsembleRetriever(
        retrievers=[faiss_ret, bm25_ret], weights=[0.5, 0.5]
    )
    hybrid_30_70 = EnsembleRetriever(
        retrievers=[faiss_ret, bm25_ret], weights=[0.3, 0.7]
    )
    return {
        "semantic_only":  ("Semantic only (FAISS)",           faiss_ret),
        "bm25_only":      ("BM25 keyword only",               bm25_ret),
        "hybrid_50_50":   ("Hybrid 50% semantic + 50% BM25",  hybrid_50),
        "hybrid_30_70":   ("Hybrid 30% semantic + 70% BM25",  hybrid_30_70),
    }

# ── Chain ─────────────────────────────────────────────────────────────────────
def make_chain(retriever):
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)
    return (
        {"context": retriever | fmt, "question": RunnablePassthrough()}
        | PROMPT | llm | StrOutputParser()
    )

# ── Scorer ────────────────────────────────────────────────────────────────────
def score_answer(question, answer, docs):
    facts     = ANSWER_FACTS.get(question, [])
    ans_lower = answer.lower()
    ctx_lower = " ".join(d.page_content for d in docs).lower()
    hits      = [f for f in facts if f in ans_lower]
    ctx_hits  = [f for f in facts if f in ctx_lower]
    refused   = any(p in ans_lower for p in [
        "does not answer", "does not contain",
        "not mentioned", "not explicitly", "not provided"
    ])
    return {
        "facts_hit":      len(hits),
        "facts_total":    len(facts),
        "score_pct":      round(100 * len(hits) / len(facts)) if facts else 0,
        "facts_found":    hits,
        "facts_missing":  [f for f in facts if f not in ans_lower],
        "ctx_fact_hits":  len(ctx_hits),
        "ctx_size_chars": sum(len(d.page_content) for d in docs),
        "refused":        refused,
        # First 120 chars of each retrieved chunk — to see WHAT was retrieved
        "top_chunk_previews": [d.page_content[:120].replace("\n", " ")
                               for d in docs],
    }

# ── Run ───────────────────────────────────────────────────────────────────────
def run():
    raw    = load_raw()
    chunks = load_chunks(raw)
    print(f"Book: {len(raw):,} chars | Chunks: {len(chunks)}\n")

    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    faiss_vs = get_faiss(embed_fn, chunks)

    print("  [build] BM25 index (in-memory, instant)...")
    t0 = time.perf_counter()
    retrievers = build_retrievers(chunks, faiss_vs)
    print(f"  [build] BM25 ready in {time.perf_counter()-t0:.1f}s\n")

    results = {}

    for strategy_key, (label, retriever) in retrievers.items():
        print(f"\n{'='*60}")
        print(f"STRATEGY: {label}")
        print('='*60)

        chain     = make_chain(retriever)
        ans_cache = ANS_DIR / f"{strategy_key}.answers.pkl"

        if ans_cache.exists():
            queries = pickle.loads(ans_cache.read_bytes())
            if len(queries) == len(QUESTIONS):
                print("  [cache] All answers loaded")
                for entry in queries:
                    s   = entry["score"]
                    tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
                    print(f"  [{tag}] [{entry['q_time']:.1f}s] {entry['q'][:55]}...")
                results[strategy_key] = {
                    "label": label, "queries": queries
                }
                continue
            print(f"  [cache] Resuming from Q{len(queries)+1}")
        else:
            queries = []

        for q in QUESTIONS[len(queries):]:
            docs = retriever.invoke(q)
            t0   = time.perf_counter()
            while True:
                try:
                    answer = chain.invoke(q)
                    break
                except Exception as e:
                    msg = str(e)
                    if any(x in msg for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                        print("    rate limit — waiting 65s...")
                        time.sleep(65)
                    else:
                        raise
            q_time = time.perf_counter() - t0
            score  = score_answer(q, answer, docs)
            queries.append({
                "q": q, "a": answer, "q_time": q_time,
                "score": score, "docs": docs,
            })
            ans_cache.write_bytes(pickle.dumps(queries))
            tag = "REFUSED" if score["refused"] else f"{score['score_pct']}%"
            print(f"  [{tag}] [{q_time:.1f}s] {q[:55]}...")

        results[strategy_key] = {"label": label, "queries": queries}

    return results

# ── Report ────────────────────────────────────────────────────────────────────
def write_report(results):
    path = Path(__file__).parent / "hybrid_report.md"
    lines = ["# Experiment 3 — Hybrid Search (Semantic + BM25)\n"]
    lines.append("**Book:** The Great Gatsby  ")
    lines.append(f"**Embedding:** {EMBED_MODEL} (fixed)  ")
    lines.append(f"**Chunk size:** {CHUNK_SIZE}, overlap={CHUNK_OVERLAP} (fixed)  ")
    lines.append(f"**k:** {K} per retriever  \n")

    # ── Summary
    lines.append("## Summary\n")
    lines.append("| Strategy | Avg Q Time | Avg Score | Q5 Answered? |")
    lines.append("|---|---|---|---|")
    for sk, r in results.items():
        avg_q  = sum(x["q_time"] for x in r["queries"]) / len(r["queries"])
        avg_s  = sum(x["score"]["score_pct"] for x in r["queries"]) / len(r["queries"])
        q5     = r["queries"][4]
        q5_tag = "NO (refused)" if q5["score"]["refused"] else \
                 ("YES" if q5["score"]["score_pct"] >= 40 else
                  f"PARTIAL ({q5['score']['score_pct']}%)")
        lines.append(f"| {r['label']} | {avg_q:.1f}s | {avg_s:.0f}% | {q5_tag} |")

    # ── Score breakdown
    lines.append("\n## Completeness Scores per Question\n")
    s_keys = list(results.keys())
    lines.append("| Question | " + " | ".join(results[k]["label"] for k in s_keys) + " |")
    lines.append("|---|" + "---|" * len(s_keys))
    for qi, q in enumerate(QUESTIONS):
        scores = []
        for sk in s_keys:
            s   = results[sk]["queries"][qi]["score"]
            tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
            scores.append(tag)
        lines.append(f"| {q[:50]} | " + " | ".join(scores) + " |")

    # ── Q5 deep dive
    lines.append("\n## Q5 Deep Dive — \"How does Gatsby die?\"\n")
    lines.append("The question that failed across all chunk sizes and k values.\n")
    for sk, r in results.items():
        entry = r["queries"][4]
        s     = entry["score"]
        lines.append(f"### {r['label']}\n")
        lines.append(f"- Facts in retrieved context: {s['ctx_fact_hits']}/{s['facts_total']}")
        lines.append(f"- Answer score: {s['score_pct']}%  |  Refused: {s['refused']}")
        lines.append(f"- Facts found: {s['facts_found']}")
        lines.append(f"- Facts missing: {s['facts_missing']}")
        lines.append(f"\n**Retrieved chunk previews:**")
        for i, preview in enumerate(s["top_chunk_previews"]):
            lines.append(f"  - Chunk {i+1}: `{preview}...`")
        wrapped = textwrap.fill(entry["a"], width=100)
        lines.append(f"\n**Answer:**\n> {wrapped.replace(chr(10), chr(10)+'> ')}\n")

    # ── Full answers
    lines.append("\n## Full Answers per Strategy\n")
    for qi, q in enumerate(QUESTIONS):
        lines.append(f"### Q{qi+1}: {q}\n")
        for sk, r in results.items():
            entry = r["queries"][qi]
            s     = entry["score"]
            tag   = "REFUSED" if s["refused"] else f"{s['score_pct']}% complete"
            lines.append(f"**{r['label']}** — {entry['q_time']:.1f}s — {tag}")
            wrapped = textwrap.fill(entry["a"], width=100)
            lines.append(f"\n> {wrapped.replace(chr(10), chr(10)+'> ')}\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved -> {path}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = run()
    write_report(results)
