"""
Experiment 2 — k (Number of Retrieved Chunks) vs Answer Quality
----------------------------------------------------------------
Fixes chunk_size=800, overlap=80, embedding=all-MiniLM-L6-v2
Varies k: 2, 4, 8, 12

Hypothesis: Q5 (Gatsby's death) failed in Exp 1 because the correct
chunk wasn't in the top-4. Does it surface with higher k?

Metrics:
  - Answer completeness score (keyword-based, same as Exp 1)
  - Whether Q5 is finally answered
  - Query time (more chunks fed to LLM = longer prompt = slower)
  - Context size (chars) fed to LLM per question

Caching: FAISS index built once (chunk_size=800 reused from Exp 1 if present).
         Answers pickled per k config — resume-safe.

Report: day2/k_report.md
Run:    python k_eval.py
"""

import os, time, pickle, textwrap
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY  = "AQ.Ab8RN6L5WoVoHIRxxx3h4PdsTuub41-kMGg_ZKZ3tdbanzhN9A"
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH  = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR  = Path(__file__).parent / "chunk_cache"   # reuse Exp 1 FAISS index
CACHE_DIR.mkdir(exist_ok=True)
ANS_DIR    = Path(__file__).parent / "k_cache"
ANS_DIR.mkdir(exist_ok=True)

EMBED_MODEL  = "all-MiniLM-L6-v2"
CHUNK_SIZE   = 800
CHUNK_OVERLAP = 80
FAISS_KEY    = "chunk800"   # matches Exp 1 cache filename

K_VALUES = [2, 4, 8, 12]

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

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    start = raw.find("*** START OF THE PROJECT GUTENBERG")
    end   = raw.find("*** END OF THE PROJECT GUTENBERG")
    if start != -1: raw = raw[raw.find("\n", start) + 1:]
    if end   != -1: raw = raw[:end]
    return raw

def get_vectorstore(embed_fn, chunks):
    cache_path = CACHE_DIR / f"{FAISS_KEY}.faiss"
    meta_path  = CACHE_DIR / f"{FAISS_KEY}.meta"

    if cache_path.exists():
        t0 = time.perf_counter()
        vs = FAISS.load_local(str(cache_path), embed_fn,
                              allow_dangerous_deserialization=True)
        load_t = time.perf_counter() - t0
        index_time = pickle.loads(meta_path.read_bytes())["index_time"]
        print(f"  [cache] FAISS loaded in {load_t:.1f}s  (built in {index_time:.1f}s)")
        return vs, index_time

    print(f"  [build] Embedding {len(chunks)} chunks ...")
    t0 = time.perf_counter()
    vs = FAISS.from_documents(chunks, embed_fn)
    index_time = time.perf_counter() - t0
    print(f"  [build] Done in {index_time:.1f}s")
    vs.save_local(str(cache_path))
    meta_path.write_bytes(pickle.dumps({"index_time": index_time}))
    return vs, index_time

def make_chain(retriever):
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)
    return (
        {"context": retriever | fmt, "question": RunnablePassthrough()}
        | PROMPT | llm | StrOutputParser()
    )

def score_answer(question, answer, retrieved_docs):
    facts      = ANSWER_FACTS.get(question, [])
    ans_lower  = answer.lower()
    ctx_lower  = " ".join(d.page_content for d in retrieved_docs).lower()
    hits       = [f for f in facts if f in ans_lower]
    ctx_hits   = [f for f in facts if f in ctx_lower]
    refused    = any(p in ans_lower for p in [
        "does not answer", "does not contain",
        "not mentioned", "not explicitly", "not provided"
    ])
    ctx_size   = sum(len(d.page_content) for d in retrieved_docs)
    return {
        "facts_hit":          len(hits),
        "facts_total":        len(facts),
        "score_pct":          round(100 * len(hits) / len(facts)) if facts else 0,
        "facts_found":        hits,
        "facts_missing":      [f for f in facts if f not in ans_lower],
        "ctx_fact_hits":      len(ctx_hits),
        "ctx_size_chars":     ctx_size,
        "refused":            refused,
    }

# ── Run ───────────────────────────────────────────────────────────────────────
def run():
    raw    = load_raw()
    print(f"Book: {len(raw):,} chars\n")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.create_documents([raw])
    print(f"Chunks (size={CHUNK_SIZE}): {len(chunks)}\n")

    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    vs, index_time = get_vectorstore(embed_fn, chunks)

    results = {}

    for k in K_VALUES:
        cfg_key = f"k{k}"
        label   = f"k={k}"
        print(f"\n{'='*60}")
        print(f"CONFIG: {label}  (retrieves top-{k} chunks per question)")
        print('='*60)

        retriever = vs.as_retriever(search_kwargs={"k": k})
        chain     = make_chain(retriever)

        ans_cache = ANS_DIR / f"{cfg_key}.answers.pkl"
        if ans_cache.exists():
            queries = pickle.loads(ans_cache.read_bytes())
            if len(queries) == len(QUESTIONS):
                print("  [cache] All answers loaded")
                for entry in queries:
                    s = entry["score"]
                    tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
                    print(f"  [{tag}] [{entry['q_time']:.1f}s] "
                          f"[ctx={s['ctx_size_chars']}c] {entry['q'][:50]}...")
                results[cfg_key] = {
                    "label": label, "k": k,
                    "index_time": index_time, "queries": queries,
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
            print(f"  [{tag}] [{q_time:.1f}s] "
                  f"[ctx={score['ctx_size_chars']}c] {q[:50]}...")

        results[cfg_key] = {
            "label": label, "k": k,
            "index_time": index_time, "queries": queries,
        }

    return results

# ── Report ────────────────────────────────────────────────────────────────────
def write_report(results):
    path = Path(__file__).parent / "k_report.md"
    lines = ["# Experiment 2 — k (Retrieved Chunks) vs Answer Quality\n"]
    lines.append("**Book:** The Great Gatsby  ")
    lines.append(f"**Embedding:** {EMBED_MODEL} (fixed)  ")
    lines.append(f"**Chunk size:** {CHUNK_SIZE}, overlap={CHUNK_OVERLAP} (fixed)  ")
    lines.append(f"**k values tested:** {K_VALUES}  \n")

    # ── Summary table
    lines.append("## Summary\n")
    lines.append("| k | Avg Q Time | Avg Context Size | Avg Score | Q5 Answered? |")
    lines.append("|---|---|---|---|---|")
    for cfg_key, r in results.items():
        avg_q   = sum(x["q_time"] for x in r["queries"]) / len(r["queries"])
        avg_ctx = sum(x["score"]["ctx_size_chars"] for x in r["queries"]) / len(r["queries"])
        avg_s   = sum(x["score"]["score_pct"] for x in r["queries"]) / len(r["queries"])
        q5      = r["queries"][4]
        q5_tag  = "NO (refused)" if q5["score"]["refused"] else \
                  ("YES" if q5["score"]["score_pct"] >= 40 else
                   f"PARTIAL ({q5['score']['score_pct']}%)")
        lines.append(
            f"| {r['k']} | {avg_q:.1f}s | {avg_ctx:.0f} chars "
            f"| {avg_s:.0f}% | {q5_tag} |"
        )

    # ── Score breakdown per question
    lines.append("\n## Completeness Scores per Question\n")
    k_keys = list(results.keys())
    lines.append("| Question | " + " | ".join(f"k={results[k]['k']}" for k in k_keys) + " |")
    lines.append("|---|" + "---|" * len(k_keys))
    for qi, q in enumerate(QUESTIONS):
        scores = []
        for k in k_keys:
            s = results[k]["queries"][qi]["score"]
            tag = "REFUSED" if s["refused"] else f"{s['score_pct']}%"
            scores.append(tag)
        lines.append(f"| {q[:50]} | " + " | ".join(scores) + " |")

    # ── Context size vs query time (shows the tradeoff)
    lines.append("\n## Context Size vs Query Time Tradeoff\n")
    lines.append("Larger k = more text fed to LLM = longer answers = slower.\n")
    lines.append("| k | Q1 ctx | Q1 time | Q3 ctx | Q3 time | Q5 ctx | Q5 time |")
    lines.append("|---|---|---|---|---|---|---|")
    for cfg_key, r in results.items():
        q1, q3, q5 = r["queries"][0], r["queries"][2], r["queries"][4]
        lines.append(
            f"| {r['k']} "
            f"| {q1['score']['ctx_size_chars']}c | {q1['q_time']:.1f}s "
            f"| {q3['score']['ctx_size_chars']}c | {q3['q_time']:.1f}s "
            f"| {q5['score']['ctx_size_chars']}c | {q5['q_time']:.1f}s |"
        )

    # ── Q5 deep dive
    lines.append("\n## Q5 Deep Dive — \"How does Gatsby die?\"\n")
    for cfg_key, r in results.items():
        entry = r["queries"][4]
        s = entry["score"]
        lines.append(f"### k={r['k']}\n")
        lines.append(f"- Context size: {s['ctx_size_chars']} chars")
        lines.append(f"- Facts in context: {s['ctx_fact_hits']}/{s['facts_total']}")
        lines.append(f"- Answer score: {s['score_pct']}%")
        lines.append(f"- Facts found: {s['facts_found']}")
        lines.append(f"- Facts missing: {s['facts_missing']}")
        lines.append(f"- Refused: {s['refused']}")
        wrapped = textwrap.fill(entry["a"], width=100)
        lines.append(f"\n> {wrapped.replace(chr(10), chr(10) + '> ')}\n")

    # ── Full answers
    lines.append("\n## Full Answers per k\n")
    for qi, q in enumerate(QUESTIONS):
        lines.append(f"### Q{qi+1}: {q}\n")
        for cfg_key, r in results.items():
            entry = r["queries"][qi]
            s = entry["score"]
            tag = "REFUSED" if s["refused"] else f"{s['score_pct']}% complete"
            lines.append(
                f"**k={r['k']}** — {entry['q_time']:.1f}s — "
                f"ctx={s['ctx_size_chars']}c — {tag}"
            )
            wrapped = textwrap.fill(entry["a"], width=100)
            lines.append(f"\n> {wrapped.replace(chr(10), chr(10) + '> ')}\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved -> {path}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = run()
    write_report(results)
