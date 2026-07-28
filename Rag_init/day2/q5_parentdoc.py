"""
Q5 Fix — Parent-Document Retriever + Inference Prompt
------------------------------------------------------
Day 2 proved Q5 ("How does Gatsby die?") has TWO stacked failures:
  1. Retrieval — the death scene never enters the top-4 (semantic mismatch).
  2. Guardrail — even hand-fed, the strict prompt refuses.

We already fixed #2 (inference prompt). This fixes #1 with a
ParentDocumentRetriever:
  - Split into SMALL child chunks (200c) -> precise semantic matching.
  - But return the LARGE parent chunk (2000c) that the child came from ->
    the LLM sees the whole surrounding scene, not a fragment.

The hope: a small child chunk near the pool matches the query, and its
parent contains "heard the shots" + "red circle" + "Wilson's body" — enough
for the inference prompt to answer.

We ask ALL 5 questions to see the net effect, but only Q5 is the target.
Answers cached — resume-safe. Report: day2/parentdoc_report.md
Run: python q5_parentdoc.py
"""

import os, time, pickle
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.stores import InMemoryStore
from langchain_classic.retrievers import ParentDocumentRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

API_KEY = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH  = Path(__file__).parent.parent / "day1" / "gatsby.txt"
ANS_CACHE  = Path(__file__).parent / "parentdoc.answers.pkl"

EMBED_MODEL = "all-MiniLM-L6-v2"

QUESTIONS = [
    "Who is Jay Gatsby and what is his dream?",
    "What does the green light symbolize?",
    "Describe the relationship between Gatsby and Daisy.",
    "Who is Nick Carraway and how does he know Gatsby?",
    "How does Gatsby die?",
]

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

# Inference prompt (the one proven in prompt_compare)
PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer based on the context below. You MAY draw reasonable logical "
    "inferences from what the context states, even if it is not spelled out "
    "word-for-word — but do NOT introduce facts that the context gives no "
    "basis for. If the context truly gives no basis for an answer, say: "
    "'The provided context does not answer this question.'\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    s = raw.find("*** START OF THE PROJECT GUTENBERG")
    e = raw.find("*** END OF THE PROJECT GUTENBERG")
    if s != -1: raw = raw[raw.find("\n", s) + 1:]
    if e != -1: raw = raw[:e]
    return raw

def build_retriever():
    from langchain_core.documents import Document
    raw = load_raw()
    parent_docs = [Document(page_content=raw)]

    # Parent = large scene (2000c), Child = small precise chunk (200c)
    parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    child_splitter  = RecursiveCharacterTextSplitter(chunk_size=200,  chunk_overlap=40)

    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    # Child vectors live in FAISS; parent docs in an in-memory docstore.
    from langchain_community.vectorstores import FAISS as FAISSVS
    # FAISS needs at least one doc to initialize; seed with a child then add all.
    seed = child_splitter.split_documents(parent_docs)[:1]
    vectorstore = FAISSVS.from_documents(seed, embed_fn)
    store = InMemoryStore()

    retriever = ParentDocumentRetriever(
        vectorstore=vectorstore,
        docstore=store,
        child_splitter=child_splitter,
        parent_splitter=parent_splitter,
        search_kwargs={"k": 3},
    )
    print("  Indexing parent/child chunks (local embeddings)...")
    t0 = time.perf_counter()
    retriever.add_documents(parent_docs)
    print(f"  Indexed in {time.perf_counter()-t0:.1f}s")
    return retriever

def run():
    retriever = build_retriever()
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)
    chain = PROMPT | llm | StrOutputParser()

    cache = pickle.loads(ANS_CACHE.read_bytes()) if ANS_CACHE.exists() else {}
    results = []
    for q in QUESTIONS:
        docs = retriever.invoke(q)
        ctx  = fmt(docs)
        # Does the retrieved context now contain the death-scene signals?
        ctx_l = ctx.lower()
        death_signals = [s for s in ["shot", "pool", "wilson", "red circle", "mattress"] if s in ctx_l]

        if q in cache:
            answer = cache[q]["a"]
            print(f"  [cache] {q[:45]}")
        else:
            while True:
                try:
                    answer = chain.invoke({"context": ctx, "question": q}); break
                except Exception as ex:
                    if any(x in str(ex) for x in ("429","RESOURCE_EXHAUSTED","503","UNAVAILABLE")):
                        print("    rate limit — waiting 65s..."); time.sleep(65)
                    else: raise
            cache[q] = {"a": answer}
            ANS_CACHE.write_bytes(pickle.dumps(cache))

        refused = "does not answer this question" in answer.lower() and len(answer) < 250
        tag = "REFUSED" if refused else "ANSWERED"
        print(f"  [{tag}] death-signals in ctx: {death_signals}  | {q[:45]}")
        results.append({"q": q, "a": answer, "refused": refused,
                        "ctx_size": len(ctx), "death_signals": death_signals,
                        "ctx_preview": ctx[:300]})
    return results

def write_report(results):
    path = Path(__file__).parent / "parentdoc_report.md"
    L = ["# Q5 Fix — Parent-Document Retriever + Inference Prompt\n"]
    L.append("**Child chunks:** 200c (matching)  |  **Parent chunks:** 2000c (fed to LLM)  ")
    L.append("**Embedding:** all-MiniLM-L6-v2  |  **Prompt:** inference-allowed  \n")

    L.append("## Results\n")
    L.append("| Question | Answered? | Death-scene signals in retrieved context |")
    L.append("|---|---|---|")
    for r in results:
        tag = "REFUSED" if r["refused"] else "ANSWERED"
        L.append(f"| {r['q'][:45]} | {tag} | {', '.join(r['death_signals']) or '—'} |")

    L.append("\n## Q5 Deep Dive — did the death scene finally get retrieved?\n")
    q5 = next(r for r in results if r["q"] == "How does Gatsby die?")
    L.append(f"- Death-scene signals now in context: **{q5['death_signals']}**")
    L.append(f"- Context size fed to LLM: {q5['ctx_size']} chars")
    L.append(f"- Answered: **{not q5['refused']}**")
    L.append(f"\n**Retrieved context preview:**\n> {q5['ctx_preview']}...\n")
    L.append(f"\n**Answer:**\n> {q5['a'][:700]}\n")

    L.append("\n## All Answers\n")
    for r in results:
        L.append(f"### {r['q']}\n")
        L.append(f"- Answered: {not r['refused']}  |  signals: {r['death_signals']}")
        L.append(f"\n> {r['a'][:600]}\n")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    results = run()
    write_report(results)
