"""
Q5 Retrieval Probe (NO LLM calls — pure retrieval diagnostics, free)
--------------------------------------------------------------------
Why does no retriever find Gatsby's death scene? Test what actually ranks
for the query vs. an EXPANDED query, on plain 800c chunks.

Compares retrieval for:
  A. Original query:  "How does Gatsby die?"
  B. Expanded query:  "Gatsby shot dead pool mattress Wilson body blood
                       gunshot murdered killed"

For each, print whether the true death-scene chunk (containing "heard the
shots" / "thin red circle" / "holocaust") appears in the top-k, and at what
rank. This isolates whether QUERY EXPANSION alone fixes Q5 — no API cost.
"""

import os
from pathlib import Path
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

BOOK_PATH = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR = Path(__file__).parent / "chunk_cache"
EMBED_MODEL = "all-MiniLM-L6-v2"

def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    s = raw.find("*** START OF THE PROJECT GUTENBERG")
    e = raw.find("*** END OF THE PROJECT GUTENBERG")
    if s != -1: raw = raw[raw.find("\n", s) + 1:]
    if e != -1: raw = raw[:e]
    return raw

# A chunk is the "death scene" if it carries these tell-tale phrases
DEATH_MARKERS = ["heard the", "thin red circle", "holocaust", "wilson's body",
                 "laden mattress"]

def is_death_chunk(text):
    t = text.lower()
    return sum(m in t for m in DEATH_MARKERS)

QUERIES = {
    "A. Original": "How does Gatsby die?",
    "B. Expanded": ("Gatsby shot dead in the pool, the mattress, Wilson's body "
                    "in the grass, gunshot, blood, murdered, killed, holocaust"),
}

def main():
    raw = load_raw()
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=80).create_documents([raw])
    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

    # Reuse the cached chunk800 FAISS index
    vs = FAISS.load_local(str(CACHE_DIR / "chunk800.faiss"), embed_fn,
                          allow_dangerous_deserialization=True)

    # First, confirm the death chunk EXISTS in the index at all
    all_death = [i for i, c in enumerate(chunks) if is_death_chunk(c.page_content)]
    print(f"Death-scene chunks in the book: {len(all_death)} "
          f"(indices {all_death})\n")
    for i in all_death:
        print(f"  chunk[{i}] preview: {chunks[i].page_content[:130].strip()!r}\n")

    for label, q in QUERIES.items():
        print(f"{'='*64}\n{label}: {q[:60]}\n{'='*64}")
        docs = vs.similarity_search(q, k=8)
        found_rank = None
        for rank, d in enumerate(docs, 1):
            score = is_death_chunk(d.page_content)
            marker = f"  <-- DEATH CHUNK (markers={score})" if score else ""
            print(f"  rank {rank}: {d.page_content[:70].strip()!r}{marker}")
            if score and found_rank is None:
                found_rank = rank
        verdict = (f"death scene found at rank {found_rank}"
                   if found_rank else "death scene NOT in top-8")
        print(f"  => {verdict}\n")

if __name__ == "__main__":
    main()
