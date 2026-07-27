"""
Day 3 · Experiment 12 — Sequential vs Async/Parallel Throughput
----------------------------------------------------------------
A production RAG serves many users at once. Answering questions one-by-one
(sequential) wastes time waiting on I/O. Answering them concurrently (async)
overlaps the network waits, dramatically improving throughput.

We answer the SAME batch of questions two ways and compare wall-clock time:
  - Sequential: await each answer before starting the next
  - Async:      fire all requests concurrently, gather results

Report: day3/async_report.md
Run:    python async_eval.py
"""

import os, time, asyncio
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

os.environ["GROQ_API_KEY"] = "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"
GROQ_MODEL = "openai/gpt-oss-120b"
CHUNK_CACHE = Path(__file__).parent.parent / "day2" / "chunk_cache"
EMBED_MODEL = "all-MiniLM-L6-v2"

embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
vs = FAISS.load_local(str(CHUNK_CACHE / "chunk800.faiss"), embed_fn,
                      allow_dangerous_deserialization=True)
llm = ChatGroq(model=GROQ_MODEL, temperature=0)
PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. Answer concisely based on the "
    "context.\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:")
chain = PROMPT | llm | StrOutputParser()

QUESTIONS = [
    "What does the green light symbolize?",
    "Describe Gatsby's parties.",
    "Who is Tom Buchanan?",
    "What is West Egg?",
    "Describe Daisy's personality.",
    "What is the valley of ashes?",
]

def ctx(q):
    return "\n\n---\n\n".join(d.page_content for d in vs.similarity_search(q, k=4))

# Pre-compute contexts (retrieval is local/fast; we're measuring LLM I/O overlap)
PAYLOADS = [{"context": ctx(q), "question": q} for q in QUESTIONS]

def run_sequential():
    t0 = time.perf_counter()
    for p in PAYLOADS:
        chain.invoke(p)
    return time.perf_counter() - t0

async def run_async():
    t0 = time.perf_counter()
    await asyncio.gather(*(chain.ainvoke(p) for p in PAYLOADS))
    return time.perf_counter() - t0

def main():
    n = len(QUESTIONS)
    print(f"Answering {n} questions...\n")

    seq = run_sequential()
    print(f"SEQUENTIAL: {seq:.2f}s total ({seq/n:.2f}s per question)")

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()) \
        if hasattr(asyncio, "WindowsSelectorEventLoopPolicy") else None
    asy = asyncio.run(run_async())
    print(f"ASYNC:      {asy:.2f}s total ({asy/n:.2f}s per question)")

    speedup = seq / asy if asy else 0
    print(f"\nSpeedup: {speedup:.1f}x\n")

    path = Path(__file__).parent / "async_report.md"
    L = ["# Day 3 · Experiment 12 — Sequential vs Async Throughput\n"]
    L.append(f"Answering the same batch of **{n} questions** two ways.\n")
    L.append("| Mode | Total time | Per question |")
    L.append("|---|---|---|")
    L.append(f"| Sequential | {seq:.2f}s | {seq/n:.2f}s |")
    L.append(f"| Async (concurrent) | **{asy:.2f}s** | {asy/n:.2f}s |")
    L.append("")
    L.append(f"- **Throughput speedup: {speedup:.1f}x** by overlapping network "
             "waits instead of blocking on each request.")
    L.append("- Retrieval was pre-computed (local, fast); the win comes from "
             "concurrent LLM I/O.")
    L.append("\n## Takeaway\n")
    L.append("- Sequential processing wastes most of its time waiting on the "
             "network. For a RAG service handling multiple users or batch jobs, "
             "async concurrency is close to free throughput — same code, "
             "`ainvoke` + `asyncio.gather` instead of a loop.")
    L.append("- The speedup is bounded by the provider's concurrency limits and "
             "the slowest single request, so it won't scale infinitely — but "
             f"going from {seq:.1f}s to {asy:.1f}s for {n} questions is real.")
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"Report saved -> {path}")

if __name__ == "__main__":
    main()
