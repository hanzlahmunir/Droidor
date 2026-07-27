"""
Day 3 · Experiment 11 — Streaming vs Non-Streaming
---------------------------------------------------
Total latency is the same, but PERCEIVED latency differs hugely: streaming
shows the first tokens almost immediately, while non-streaming shows nothing
until the whole answer is ready.

We measure, for the same question:
  - Non-streaming: time to full answer (user sees nothing until then)
  - Streaming:     time-to-first-token (TTFT) + time to full answer

TTFT is the number that matters for UX — how long the user stares at a blank
screen. Report: day3/streaming_report.md
Run:   python streaming_eval.py
"""

import os, time
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
    "You are an expert on 'The Great Gatsby'. Answer based on the context.\n\n"
    "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:")

QUESTION = "Describe the relationship between Gatsby and Daisy in detail."

def ctx():
    return "\n\n---\n\n".join(d.page_content for d in vs.similarity_search(QUESTION, k=4))

def run():
    context = ctx()
    payload = {"context": context, "question": QUESTION}

    # ── Non-streaming ─────────────────────────────────────────────────────────
    chain = PROMPT | llm | StrOutputParser()
    t0 = time.perf_counter()
    full = chain.invoke(payload)
    non_stream_total = time.perf_counter() - t0
    print(f"NON-STREAMING: user waits {non_stream_total:.2f}s seeing nothing, "
          f"then the whole {len(full)}-char answer appears at once.\n")

    # ── Streaming ─────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    ttft = None
    chunks = 0
    collected = ""
    for piece in chain.stream(payload):
        if ttft is None and piece.strip():
            ttft = time.perf_counter() - t0
        collected += piece
        chunks += 1
    stream_total = time.perf_counter() - t0
    print(f"STREAMING: first token at {ttft:.2f}s (user starts reading), "
          f"{chunks} chunks, full answer at {stream_total:.2f}s.\n")

    write_report(non_stream_total, ttft, stream_total, chunks, full)

def write_report(non_stream_total, ttft, stream_total, chunks, full):
    path = Path(__file__).parent / "streaming_report.md"
    speedup = non_stream_total / ttft if ttft else 0
    L = ["# Day 3 · Experiment 11 — Streaming vs Non-Streaming\n"]
    L.append(f"**Question:** {QUESTION}\n")
    L.append("## Latency\n")
    L.append("| Mode | Time to first visible token | Time to full answer |")
    L.append("|---|---|---|")
    L.append(f"| Non-streaming | {non_stream_total:.2f}s (blank until done) | {non_stream_total:.2f}s |")
    L.append(f"| Streaming | **{ttft:.2f}s** | {stream_total:.2f}s |")
    L.append("")
    L.append(f"- **Perceived-latency improvement: {speedup:.1f}x** — the user "
             f"starts reading at {ttft:.2f}s instead of {non_stream_total:.2f}s.")
    L.append(f"- Streaming delivered the answer in {chunks} incremental chunks.")
    L.append(f"- **Total time is ~the same**; streaming wins purely on UX — the "
             "user is never staring at a blank screen.\n")
    L.append("## Takeaway\n")
    L.append("- For any user-facing RAG app, stream. Total compute is identical, "
             "but time-to-first-token is what users actually feel. A 2-3s wait "
             "for a full answer feels slow; the same answer streaming from "
             "~0.3s feels instant.")
    L.append(f"\n## Sample answer\n> {full[:500]}\n")
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"Report saved -> {path}")

if __name__ == "__main__":
    run()
