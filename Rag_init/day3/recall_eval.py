"""
Day 3 · Experiment 6 — Retrieval Evaluation (Recall@k)
-------------------------------------------------------
Every prior experiment judged retrieval INDIRECTLY via answer quality. But a
wrong answer could mean bad retrieval OR bad generation. Recall@k measures
retrieval DIRECTLY and separates the two failure modes.

For each question we define a GROUND-TRUTH chunk by a distinctive phrase that
only appears in the passage actually containing the answer. Then we ask: does
the retriever surface that chunk within the top-k?

  Recall@k = 1 if a ground-truth chunk is in the top-k results, else 0
  MRR      = 1 / (rank of first ground-truth chunk), 0 if not found

We evaluate across k ∈ {1,2,4,8,12} and across retrieval strategies
(semantic, BM25, hybrid) — ZERO LLM calls, completely free.

This finally answers, per question: "was the failure retrieval or generation?"

Report: day3/recall_report.md
Run:    python recall_eval.py
"""

import os
from pathlib import Path
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter

BOOK_PATH   = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CHUNK_CACHE = Path(__file__).parent.parent / "day2" / "chunk_cache"
EMBED_MODEL = "all-MiniLM-L6-v2"

# ── Questions + a distinctive phrase that marks the ground-truth chunk ─────────
# The phrase must be verbatim in the passage that answers the question.
GROUND_TRUTH = {
    "What does the green light symbolize?":
        "orgiastic future",
    "How does Gatsby die?":
        "holocaust was complete",
    "Describe the relationship between Gatsby and Daisy.":
        "he felt married to her",
    "Who is Nick Carraway and how does he know Gatsby?":
        "bond business",
    "What is the last line of the book?":
        "borne back ceaselessly into the past",
}

def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    s = raw.find("*** START OF THE PROJECT GUTENBERG")
    e = raw.find("*** END OF THE PROJECT GUTENBERG")
    if s != -1: raw = raw[raw.find("\n", s) + 1:]
    if e != -1: raw = raw[:e]
    return raw

import re as _re
def chunk_has_truth(text, phrase):
    # Chunk text contains newlines mid-phrase ("holocaust\nwas complete");
    # normalize whitespace on both sides before matching.
    flat = _re.sub(r"\s+", " ", text).lower()
    ph   = _re.sub(r"\s+", " ", phrase).lower()
    return ph in flat

def main():
    raw = load_raw()
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=80).create_documents([raw])
    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

    faiss_vs = FAISS.load_local(str(CHUNK_CACHE / "chunk800.faiss"), embed_fn,
                                allow_dangerous_deserialization=True)

    # Verify every ground-truth phrase actually exists in exactly some chunk(s)
    print("Ground-truth chunk check:")
    truth_index = {}
    for q, phrase in GROUND_TRUTH.items():
        idxs = [i for i, c in enumerate(chunks) if chunk_has_truth(c.page_content, phrase)]
        truth_index[q] = idxs
        status = "OK" if idxs else "MISSING!"
        print(f"  [{status}] {phrase!r} -> chunks {idxs}")
    print()

    K_VALUES = [1, 2, 4, 8, 12]

    # Build the three retrieval strategies
    bm25 = BM25Retriever.from_documents(chunks, k=12)
    faiss_ret = faiss_vs.as_retriever(search_kwargs={"k": 12})
    hybrid = EnsembleRetriever(retrievers=[faiss_ret, bm25], weights=[0.3, 0.7])

    strategies = {
        "semantic": lambda q: faiss_vs.similarity_search(q, k=12),
        "bm25":     lambda q: bm25.invoke(q),
        "hybrid":   lambda q: hybrid.invoke(q),
    }

    # results[strategy][q] = ranked list of bools (is chunk a truth chunk?)
    results = {}
    for sname, retrieve in strategies.items():
        results[sname] = {}
        for q, phrase in GROUND_TRUTH.items():
            docs = retrieve(q)
            hit_ranks = [i+1 for i, d in enumerate(docs)
                         if chunk_has_truth(d.page_content, phrase)]
            results[sname][q] = hit_ranks

    write_report(results, K_VALUES)

def write_report(results, K_VALUES):
    path = Path(__file__).parent / "recall_report.md"
    L = ["# Day 3 · Experiment 6 — Retrieval Evaluation (Recall@k)\n"]
    L.append("Measures retrieval DIRECTLY: does the ground-truth chunk (marked by "
             "a distinctive verbatim phrase) appear in the top-k? Zero LLM calls.\n")
    L.append("- **Recall@k** = ground-truth chunk is within top-k (1/0)")
    L.append("- **MRR** = 1 / rank of first ground-truth chunk\n")

    for sname, per_q in results.items():
        L.append(f"## Strategy: {sname}\n")
        header = "| Question | " + " | ".join(f"R@{k}" for k in K_VALUES) + " | MRR | First rank |"
        L.append(header)
        L.append("|---|" + "---|" * (len(K_VALUES) + 2))
        recall_at = {k: 0 for k in K_VALUES}
        mrr_sum = 0
        for q, hit_ranks in per_q.items():
            first = min(hit_ranks) if hit_ranks else None
            row = [q[:38]]
            for k in K_VALUES:
                hit = any(r <= k for r in hit_ranks)
                row.append("✅" if hit else "—")
                if hit: recall_at[k] += 1
            mrr = round(1/first, 3) if first else 0
            mrr_sum += mrr
            row.append(str(mrr))
            row.append(str(first) if first else "not found")
            L.append("| " + " | ".join(row) + " |")
        n = len(per_q)
        avg_row = ["**Average**"]
        for k in K_VALUES:
            avg_row.append(f"**{recall_at[k]}/{n}**")
        avg_row.append(f"**{round(mrr_sum/n,3)}**")
        avg_row.append("")
        L.append("| " + " | ".join(avg_row) + " |")
        L.append("")

    L.append("## Interpretation\n")
    L.append("- **High recall + wrong answer** = the retriever found the right "
             "chunk but GENERATION failed (prompt too strict, poor synthesis).")
    L.append("- **Low recall** = the RETRIEVER failed; no prompt fix can help.")
    L.append("- This cleanly separates the two failure modes we kept conflating "
             "in Days 1–2. Q5 ('how does Gatsby die') is the key case: if recall "
             "is low here, it confirms the vocabulary-gap diagnosis — the death "
             "chunk simply isn't retrieved by the plain query.")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"Report saved -> {path}")

if __name__ == "__main__":
    main()
