"""
Embedding Model Evaluation on The Great Gatsby
-----------------------------------------------
Tests 4 embedding models, caches indexes to disk so embeddings are
computed only once. Measures indexing time, query time, and answer
quality (hallucination check via retrieved context).

Run: python embedding_eval.py
Report saved to: embedding_report.md
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
API_KEY   = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH  = Path(__file__).parent / "gatsby.txt"
CACHE_DIR  = Path(__file__).parent / "embed_cache"
CACHE_DIR.mkdir(exist_ok=True)

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

# ── Embedding model registry ──────────────────────────────────────────────────
MODELS = {
    "all-MiniLM-L6-v2": {
        "label": "all-MiniLM-L6-v2 (local, 384-dim, fast)",
        "factory": lambda: HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2"),
        "cloud": False,
    },
    "all-mpnet-base-v2": {
        "label": "all-mpnet-base-v2 (local, 768-dim, balanced)",
        "factory": lambda: HuggingFaceEmbeddings(model_name="all-mpnet-base-v2"),
        "cloud": False,
    },
    "nomic-ai/nomic-embed-text-v1": {
        "label": "nomic-embed-text-v1 (local, 768-dim, high quality)",
        "factory": lambda: HuggingFaceEmbeddings(
            model_name="nomic-ai/nomic-embed-text-v1",
            model_kwargs={"trust_remote_code": True},
        ),
        "cloud": False,
    },
}

QUESTIONS = [
    "Who is Jay Gatsby and what is his dream?",
    "What does the green light symbolize?",
    "Describe the relationship between Gatsby and Daisy.",
    "Who is Nick Carraway and how does he know Gatsby?",
    "How does Gatsby die?",
]

# ── Load & chunk book ─────────────────────────────────────────────────────────
def load_chunks():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    start = raw.find("*** START OF THE PROJECT GUTENBERG")
    end   = raw.find("*** END OF THE PROJECT GUTENBERG")
    if start != -1: raw = raw[raw.find("\n", start) + 1:]
    if end   != -1: raw = raw[:end]
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    return splitter.create_documents([raw])

# ── Build or load FAISS index ─────────────────────────────────────────────────
def get_vectorstore(model_key, embed_fn, chunks):
    cache_path = CACHE_DIR / f"{model_key.replace('/', '_')}.faiss"
    meta_path  = CACHE_DIR / f"{model_key.replace('/', '_')}.meta"

    if cache_path.exists():
        print(f"  [cache] Loading saved index for {model_key}")
        t0 = time.perf_counter()
        vs = FAISS.load_local(str(cache_path), embed_fn, allow_dangerous_deserialization=True)
        elapsed = time.perf_counter() - t0
        index_time = pickle.loads(meta_path.read_bytes())["index_time"]
        print(f"  [cache] Loaded in {elapsed:.1f}s  (original index time: {index_time:.1f}s)")
        return vs, index_time

    print(f"  [build] Embedding {len(chunks)} chunks with {model_key} ...")
    t0 = time.perf_counter()

    if MODELS[model_key]["cloud"]:
        # Batch with rate-limit retry for Gemini
        import time as _t
        BATCH = 80
        vs = None
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i: i + BATCH]
            while True:
                try:
                    if vs is None:
                        vs = FAISS.from_documents(batch, embed_fn)
                    else:
                        vs.add_documents(batch)
                    print(f"    chunks {i+1}–{min(i+BATCH, len(chunks))} done")
                    break
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        print("    rate limit — waiting 62s...")
                        _t.sleep(62)
                    elif "ReadTimeout" in msg or "10060" in msg or "connection" in msg.lower():
                        print("    timeout — retrying in 10s...")
                        _t.sleep(10)
                    else:
                        raise
    else:
        vs = FAISS.from_documents(chunks, embed_fn)

    index_time = time.perf_counter() - t0
    print(f"  [build] Done in {index_time:.1f}s")

    vs.save_local(str(cache_path))
    meta_path.write_bytes(pickle.dumps({"index_time": index_time}))
    return vs, index_time

# ── RAG chain ─────────────────────────────────────────────────────────────────
PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer using ONLY the context below. "
    "If unsure, say so — do NOT make up information.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

def make_chain(retriever):
    def fmt(docs): return "\n\n---\n\n".join(d.page_content for d in docs)
    return (
        {"context": retriever | fmt, "question": RunnablePassthrough()}
        | PROMPT | llm | StrOutputParser()
    )

# ── Hallucination check ───────────────────────────────────────────────────────
def check_hallucination(answer: str, retrieved_docs) -> str:
    """
    Simple heuristic: flag if the answer contains a named claim that
    isn't found in any retrieved chunk. Returns 'CLEAN' or 'SUSPECT'.
    """
    combined = " ".join(d.page_content for d in retrieved_docs).lower()
    # Extract capitalized proper-noun phrases from answer
    names = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', answer)
    suspect = [n for n in names if n.lower() not in combined and len(n) > 4]
    if suspect:
        return f"SUSPECT (terms not in context: {', '.join(set(suspect[:3]))})"
    return "CLEAN"

# ── Run evaluation ────────────────────────────────────────────────────────────
def run():
    chunks = load_chunks()
    print(f"Book chunks: {len(chunks)}\n")

    results = {}  # model_key -> {index_time, queries: [{q, a, q_time, hallucination, docs}]}

    for model_key, cfg in MODELS.items():
        print(f"\n{'='*60}")
        print(f"MODEL: {cfg['label']}")
        print('='*60)

        embed_fn = cfg["factory"]()
        vs, index_time = get_vectorstore(model_key, embed_fn, chunks)
        retriever = vs.as_retriever(search_kwargs={"k": 4})
        chain = make_chain(retriever)

        ans_cache = CACHE_DIR / f"{model_key.replace('/', '_')}.answers.pkl"
        if ans_cache.exists():
            queries = pickle.loads(ans_cache.read_bytes())
            if len(queries) == len(QUESTIONS):
                print(f"  [cache] Loading saved answers")
                for entry in queries:
                    status = "OK" if entry["hallucination"] == "CLEAN" else "!!"
                    print(f"  {status} [{entry['q_time']:.1f}s] {entry['q'][:55]}...")
                results[model_key] = {"label": cfg["label"], "index_time": index_time, "queries": queries}
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
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                        print(f"    API limit/unavailable, waiting 62s...")
                        time.sleep(62)
                    else:
                        raise
            q_time = time.perf_counter() - t0
            hall = check_hallucination(answer, docs)
            queries.append({"q": q, "a": answer, "q_time": q_time, "hallucination": hall, "docs": docs})
            ans_cache.write_bytes(pickle.dumps(queries))  # save after each answer
            status = "OK" if hall == "CLEAN" else "!!"
            print(f"  {status} [{q_time:.1f}s] {q[:55]}...")

        results[model_key] = {"label": cfg["label"], "index_time": index_time, "queries": queries}

    return results

# ── Write report ──────────────────────────────────────────────────────────────
def write_report(results):
    report_path = Path(__file__).parent / "embedding_report.md"
    lines = ["# Embedding Model Evaluation — The Great Gatsby\n"]
    lines.append("**Book:** The Great Gatsby by F. Scott Fitzgerald  ")
    lines.append("**Chunks:** 452 (800 chars, 100 overlap)  ")
    lines.append(f"**Questions:** {len(QUESTIONS)}  \n")

    # Summary table
    lines.append("## Summary\n")
    lines.append("| Model | Index Time | Avg Query Time | Hallucinations |")
    lines.append("|---|---|---|---|")
    for mk, r in results.items():
        avg_q = sum(x["q_time"] for x in r["queries"]) / len(r["queries"])
        suspects = sum(1 for x in r["queries"] if x["hallucination"] != "CLEAN")
        lines.append(f"| {r['label']} | {r['index_time']:.1f}s | {avg_q:.2f}s | {suspects}/{len(QUESTIONS)} |")

    # Per-question answers
    lines.append("\n## Answers per Model\n")
    for qi, q in enumerate(QUESTIONS):
        lines.append(f"### Q{qi+1}: {q}\n")
        for mk, r in results.items():
            entry = r["queries"][qi]
            hall_badge = "🟢 CLEAN" if entry["hallucination"] == "CLEAN" else f"🔴 {entry['hallucination']}"
            lines.append(f"**{r['label']}** — {entry['q_time']:.2f}s — {hall_badge}")
            wrapped = textwrap.fill(entry["a"], width=100)
            lines.append(f"\n> {wrapped.replace(chr(10), chr(10)+'> ')}\n")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n\nReport saved -> {report_path}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = run()
    write_report(results)
