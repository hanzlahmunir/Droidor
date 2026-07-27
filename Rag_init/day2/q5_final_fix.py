"""
Q5 FINAL FIX — Query Expansion (HyDE-style) + Inference Prompt
--------------------------------------------------------------
The retrieval probe proved: the death scene sits at rank 1 IF the query
contains the scene's vocabulary. So we do two LLM steps:

  STEP 1 (expand): ask the LLM to write a hypothetical answer / keyword-rich
          version of the question — a mini-HyDE. This is done from GENERAL
          knowledge of the query type, NOT from the book, so it's cheap.
  STEP 2 (retrieve with expanded text): embed the expanded text, find the
          top-k chunks (now including the death scene).
  STEP 3 (answer): feed those chunks to the inference prompt.

Confirms Q5 finally answers end-to-end. ~2 API calls (expand + answer).
Report: appended to parentdoc_report findings.
Run: python q5_final_fix.py
"""

import os, time
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

os.environ["GROQ_API_KEY"] = "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"

CACHE_DIR = Path(__file__).parent / "chunk_cache"
EMBED_MODEL = "all-MiniLM-L6-v2"
QUESTION = "How does Gatsby die?"

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)  # gpt-oss-120b TPD exhausted

# STEP 1 — HyDE-style expansion. Note: we ask for a GENERIC hypothetical
# passage, which produces the vocabulary a death scene would use, WITHOUT
# claiming it's from the book. This bridges the query-document vocab gap.
#
# UPDATE (day 3): generic HyDE under-performed — the LLM wrote a clinical
# modern passage whose embedding missed Fitzgerald's oblique prose. We switch
# to MULTI-QUERY expansion: generate several DIVERSE plot-event rephrasings so
# at least one matches the source register, then union their retrievals.
EXPAND_PROMPT = ChatPromptTemplate.from_template(
    "Rephrase the question below into 5 diverse search queries that describe "
    "the SAME event using different concrete vocabulary — include plausible "
    "plot-event phrasings (who did what, physical details, cause). "
    "Output ONLY the 5 queries, one per line, no numbering.\n\n"
    "Question: {question}\n\nQueries:"
)

ANSWER_PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer based on the context below. You MAY draw reasonable logical "
    "inferences from what the context states, even if it is not spelled out "
    "word-for-word — but do NOT introduce facts that the context gives no "
    "basis for. If the context truly gives no basis for an answer, say: "
    "'The provided context does not answer this question.'\n\n"
    "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
)

def call(chain, payload):
    while True:
        try:
            return chain.invoke(payload)
        except Exception as e:
            if any(x in str(e) for x in ("429","RESOURCE_EXHAUSTED","503","UNAVAILABLE")):
                print("    rate limit — waiting 65s..."); time.sleep(65)
            else: raise

def main():
    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    vs = FAISS.load_local(str(CACHE_DIR / "chunk800.faiss"), embed_fn,
                          allow_dangerous_deserialization=True)

    # STEP 1 — multi-query expansion
    expand_chain = EXPAND_PROMPT | llm | StrOutputParser()
    hypo = call(expand_chain, {"question": QUESTION})
    subqueries = [q.strip("-•* \t") for q in hypo.splitlines() if q.strip()]
    print("=== STEP 1: multi-query expansion ===")
    for sq in subqueries:
        print(f"  - {sq}")
    print()

    # STEP 2 — retrieve for EACH subquery + the original, union & dedupe by content
    death_markers = ["heard the", "thin red circle", "holocaust",
                     "wilson's body", "laden mattress", "movement of the water"]
    all_queries = [QUESTION] + subqueries
    seen = {}
    for q in all_queries:
        for d in vs.similarity_search(q, k=3):
            seen[d.page_content] = d
    docs = list(seen.values())[:6]  # cap context at 6 unique chunks
    ctx = "\n\n---\n\n".join(d.page_content for d in docs)
    hits = [m for m in death_markers if m in ctx.lower()]
    print("=== STEP 2: unioned retrieval across all queries ===")
    print(f"  unique chunks gathered: {len(seen)} (using top {len(docs)})")
    for i, d in enumerate(docs, 1):
        print(f"  chunk {i}: {d.page_content[:70].strip()!r}")
    print(f"  death-scene markers now in context: {hits}\n")

    # STEP 3 — answer
    answer_chain = ANSWER_PROMPT | llm | StrOutputParser()
    answer = call(answer_chain, {"context": ctx, "question": QUESTION})
    refused = "does not answer this question" in answer.lower() and len(answer) < 250
    print("=== STEP 3: final answer ===")
    print(f"[{'REFUSED' if refused else 'ANSWERED'}]")
    print(answer)

    # Append result to report
    report = Path(__file__).parent / "q5_final_fix_report.md"
    L = ["# Q5 FINAL FIX — Multi-Query Expansion + Inference Prompt\n"]
    L.append(f"**Question:** {QUESTION}\n")
    L.append("## Step 1 — Multi-query expansion (LLM rephrases into diverse queries)\n")
    for sq in subqueries:
        L.append(f"- {sq}")
    L.append("")
    L.append("## Step 2 — Unioned retrieval across all queries\n")
    L.append(f"- Death-scene markers now in retrieved context: **{hits}**")
    L.append(f"- Retrieved chunks:")
    for i, d in enumerate(docs, 1):
        L.append(f"  {i}. `{d.page_content[:90].strip()}...`")
    L.append("\n## Step 3 — Final answer\n")
    L.append(f"- Answered: **{not refused}**\n")
    L.append(f"> {answer}\n")
    L.append("\n## Verdict\n")
    if not refused and hits:
        L.append("**Q5 SOLVED.** Query expansion bridged the query-document "
                 "vocabulary gap, pulling the death scene into context; the "
                 "inference prompt then answered it. This required BOTH fixes "
                 "(retrieval + prompt), exactly as Day 2 predicted.")
    else:
        L.append("Still unresolved — see retrieved context above.")
    report.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {report}")

if __name__ == "__main__":
    main()
