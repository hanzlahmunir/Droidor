"""
Experiment 1 — Chunk Size vs Retrieval Precision
-------------------------------------------------
Fixes one embedding model (all-MiniLM-L6-v2) and varies chunk size:
    200, 400, 800, 1600 chars  (overlap = 10% of chunk size)

Measures per chunk-size config:
  - Number of chunks produced
  - FAISS index build time (cached to disk)
  - Per-question: answer, query time, whether key facts appear in answer
  - Specific watch: does Q5 (Gatsby's death) get answered correctly?

Caching: FAISS index + answers pickled per config — resume-safe.
Report:  day2/chunk_report.md

Run: python chunk_eval.py
"""

import os, time, pickle, textwrap, re
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY  = "AQ.Ab8RN6KYb9ZmoBn91Rj_GE6Eo31GqMDkOJHSi0fLiAqUblajUw"
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR = Path(__file__).parent / "chunk_cache"
CACHE_DIR.mkdir(exist_ok=True)

# Fixed embedding model — fastest indexing so we can iterate quickly
EMBED_MODEL = "all-MiniLM-L6-v2"

# Chunk sizes to test; overlap = 10% of chunk size
CHUNK_CONFIGS = [
    {"size": 200,  "overlap": 20},
    {"size": 400,  "overlap": 40},
    {"size": 800,  "overlap": 80},
    {"size": 1600, "overlap": 160},
]

QUESTIONS = [
    "Who is Jay Gatsby and what is his dream?",
    "What does the green light symbolize?",
    "Describe the relationship between Gatsby and Daisy.",
    "Who is Nick Carraway and how does he know Gatsby?",
    "How does Gatsby die?",   # ← Q5: was unanswered in Day 1 — key test
]

# Known facts that SHOULD appear in a correct answer to each question
# Used to score answer completeness objectively (no LLM call needed)
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

# ── FAISS index — build or load ───────────────────────────────────────────────
def get_vectorstore(cfg_key, chunks, embed_fn):
    cache_path = CACHE_DIR / f"{cfg_key}.faiss"
    meta_path  = CACHE_DIR / f"{cfg_key}.meta"

    if cache_path.exists():
        t0 = time.perf_counter()
        vs = FAISS.load_local(str(cache_path), embed_fn,
                              allow_dangerous_deserialization=True)
        load_time = time.perf_counter() - t0
        index_time = pickle.loads(meta_path.read_bytes())["index_time"]
        print(f"  [cache] index loaded in {load_time:.1f}s  "
              f"(original build: {index_time:.1f}s)")
        return vs, index_time

    print(f"  [build] Embedding {len(chunks)} chunks ...")
    t0 = time.perf_counter()
    vs = FAISS.from_documents(chunks, embed_fn)
    index_time = time.perf_counter() - t0
    print(f"  [build] Done in {index_time:.1f}s")
    vs.save_local(str(cache_path))
    meta_path.write_bytes(pickle.dumps({"index_time": index_time}))
    return vs, index_time

# ── RAG chain ─────────────────────────────────────────────────────────────────
def make_chain(retriever):
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)
    return (
        {"context": retriever | fmt, "question": RunnablePassthrough()}
        | PROMPT | llm | StrOutputParser()
    )

# ── Completeness scorer ───────────────────────────────────────────────────────
def score_answer(question, answer, retrieved_docs):
    """
    Returns a dict:
      facts_hit   — how many expected keywords appear in the answer
      facts_total — total expected keywords
      score_pct   — percentage 0-100
      refused     — True if the LLM said it couldn't answer
      retrieved_relevant — True if expected keywords appear in retrieved chunks
    """
    facts = ANSWER_FACTS.get(question, [])
    ans_lower = answer.lower()
    combined_ctx = " ".join(d.page_content for d in retrieved_docs).lower()

    hits = [f for f in facts if f in ans_lower]
    ctx_hits = [f for f in facts if f in combined_ctx]

    refused = "does not answer this question" in ans_lower or \
              "does not contain" in ans_lower or \
              "not mentioned" in ans_lower or \
              "not explicitly" in ans_lower

    return {
        "facts_hit":           len(hits),
        "facts_total":         len(facts),
        "score_pct":           round(100 * len(hits) / len(facts)) if facts else 0,
        "facts_found":         hits,
        "facts_missing":       [f for f in facts if f not in ans_lower],
        "retrieved_relevant":  len(ctx_hits) > 0,
        "ctx_fact_hits":       len(ctx_hits),
        "refused":             refused,
    }

# ── Run evaluation ────────────────────────────────────────────────────────────
def run():
    raw = load_raw()
    print(f"Book: {len(raw):,} chars\n")

    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    results  = {}

    for cfg in CHUNK_CONFIGS:
        size    = cfg["size"]
        overlap = cfg["overlap"]
        cfg_key = f"chunk{size}"
        label   = f"chunk_size={size}, overlap={overlap}"

        print(f"\n{'='*60}")
        print(f"CONFIG: {label}")
        print('='*60)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size, chunk_overlap=overlap
        )
        chunks = splitter.create_documents([raw])
        print(f"  Chunks produced: {len(chunks)}")

        vs, index_time = get_vectorstore(cfg_key, chunks, embed_fn)
        retriever = vs.as_retriever(search_kwargs={"k": 4})
        chain     = make_chain(retriever)

        ans_cache = CACHE_DIR / f"{cfg_key}.answers.pkl"
        if ans_cache.exists():
            queries = pickle.loads(ans_cache.read_bytes())
            if len(queries) == len(QUESTIONS):
                print("  [cache] All answers loaded")
                for entry in queries:
                    s = entry["score"]
                    tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
                    print(f"  [{tag}] [{entry['q_time']:.1f}s] {entry['q'][:55]}...")
                results[cfg_key] = {
                    "label": label, "size": size, "overlap": overlap,
                    "n_chunks": len(chunks), "index_time": index_time,
                    "queries": queries,
                }
                continue
            print(f"  [cache] Resuming from Q{len(queries)+1}")
        else:
            queries = []

        for q in QUESTIONS[len(queries):]:
            docs = retriever.invoke(q)
            t0 = time.perf_counter()
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

        results[cfg_key] = {
            "label": label, "size": size, "overlap": overlap,
            "n_chunks": len(chunks), "index_time": index_time,
            "queries": queries,
        }

    return results

# ── Report ────────────────────────────────────────────────────────────────────
def write_report(results):
    path = Path(__file__).parent / "chunk_report.md"
    lines = ["# Experiment 1 — Chunk Size vs Retrieval Precision\n"]
    lines.append("**Book:** The Great Gatsby  ")
    lines.append(f"**Embedding:** {EMBED_MODEL} (fixed)  ")
    lines.append("**k (retrieved chunks):** 4 (fixed)  ")
    lines.append(f"**Configs tested:** {len(results)}  \n")

    # ── Summary table
    lines.append("## Summary\n")
    lines.append("| Chunk Size | Overlap | # Chunks | Index Time | Avg Q Time | Avg Score | Q5 Answered? |")
    lines.append("|---|---|---|---|---|---|---|")
    for cfg_key, r in results.items():
        avg_q   = sum(x["q_time"] for x in r["queries"]) / len(r["queries"])
        avg_s   = sum(x["score"]["score_pct"] for x in r["queries"]) / len(r["queries"])
        q5      = r["queries"][4]
        q5_tag  = "NO (refused)" if q5["score"]["refused"] else \
                  ("YES" if q5["score"]["score_pct"] >= 40 else f"PARTIAL ({q5['score']['score_pct']}%)")
        lines.append(
            f"| {r['size']} | {r['overlap']} | {r['n_chunks']} "
            f"| {r['index_time']:.1f}s | {avg_q:.1f}s "
            f"| {avg_s:.0f}% | {q5_tag} |"
        )

    # ── Completeness breakdown
    lines.append("\n## Completeness Scores per Question\n")
    lines.append("Score = % of expected answer keywords found in the LLM answer.\n")
    cfg_keys = list(results.keys())
    header = "| Question | " + " | ".join(f"size={results[k]['size']}" for k in cfg_keys) + " |"
    sep    = "|---|" + "---|" * len(cfg_keys)
    lines.append(header)
    lines.append(sep)
    for qi, q in enumerate(QUESTIONS):
        short_q = q[:50]
        scores  = []
        for k in cfg_keys:
            s = results[k]["queries"][qi]["score"]
            tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
            scores.append(tag)
        lines.append(f"| {short_q} | " + " | ".join(scores) + " |")

    # ── Retrieval coverage (did retrieved chunks even contain the answer?)
    lines.append("\n## Retrieval Coverage\n")
    lines.append("Did the retrieved chunks contain the expected keywords at all?\n")
    lines.append("| Question | " + " | ".join(f"size={results[k]['size']}" for k in cfg_keys) + " |")
    lines.append("|---|" + "---|" * len(cfg_keys))
    for qi, q in enumerate(QUESTIONS):
        short_q = q[:50]
        tags = []
        for k in cfg_keys:
            s = results[k]["queries"][qi]["score"]
            tags.append(f"{s['ctx_fact_hits']}/{s['facts_total']} facts")
        lines.append(f"| {short_q} | " + " | ".join(tags) + " |")

    # ── Key finding: Q5 deep dive
    lines.append("\n## Q5 Deep Dive — \"How does Gatsby die?\"\n")
    lines.append("This question failed across all models in Day 1. Tracking if chunk size fixes it.\n")
    for k, r in results.items():
        entry = r["queries"][4]
        s = entry["score"]
        lines.append(f"### {r['label']}\n")
        lines.append(f"- Query time: {entry['q_time']:.1f}s")
        lines.append(f"- Context contained relevant facts: {s['ctx_fact_hits']}/{s['facts_total']}")
        lines.append(f"- Answer score: {s['score_pct']}%")
        lines.append(f"- Keywords found: {s['facts_found']}")
        lines.append(f"- Keywords missing: {s['facts_missing']}")
        lines.append(f"- Refused to answer: {s['refused']}")
        wrapped = textwrap.fill(entry["a"], width=100)
        lines.append(f"\n> {wrapped.replace(chr(10), chr(10) + '> ')}\n")

    # ── Per-question full answers
    lines.append("\n## Full Answers per Config\n")
    for qi, q in enumerate(QUESTIONS):
        lines.append(f"### Q{qi+1}: {q}\n")
        for k, r in results.items():
            entry = r["queries"][qi]
            s = entry["score"]
            tag = "REFUSED" if s["refused"] else f"{s['score_pct']}% complete"
            lines.append(f"**{r['label']}** — {entry['q_time']:.1f}s — {tag}")
            wrapped = textwrap.fill(entry["a"], width=100)
            lines.append(f"\n> {wrapped.replace(chr(10), chr(10) + '> ')}\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved -> {path}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = run()
    write_report(results)
