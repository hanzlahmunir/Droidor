"""
Day 3 — Experiment 7: Agentic RAG vs Passive RAG
-------------------------------------------------
Passive RAG (Day 1-2): fixed pipeline — always retrieve top-k once, then answer.
Agentic RAG (this):     the LLM gets a `search_book` TOOL and decides for itself
                        WHEN to search, WHAT to search for, and whether to search
                        AGAIN before answering.

Why it should win:
  - Multi-hop questions ("compare X and Y") need multiple retrievals — an agent
    can call search_book twice; passive RAG retrieves once and misses half.
  - Vocabulary-gap questions (Q5!) — the agent can reformulate its own query
    ("how does Gatsby die" -> "Gatsby shot pool Wilson") when the first search
    comes back empty. This is exactly the fix we hand-built in Day 2, but the
    agent does it autonomously.

We compare PASSIVE vs AGENTIC on the same questions, including a NEW multi-hop
question that passive RAG structurally cannot answer well.

Caching: agent runs are cached per question (agent.cache.pkl) — resume-safe.
Report:  day3/agentic_report.md
Run:     python agentic_rag.py
"""

import os, time, pickle
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langgraph.prebuilt import create_react_agent

# Groq — high rate limits + fast inference, so agentic bursts don't throttle
os.environ["GROQ_API_KEY"] = "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"
GROQ_MODEL = "llama-3.3-70b-versatile"

CHUNK_CACHE = Path(__file__).parent.parent / "day2" / "chunk_cache"
ANS_CACHE   = Path(__file__).parent / "agent.cache.pkl"
EMBED_MODEL = "all-MiniLM-L6-v2"

# ── Shared retriever (reuse Day 2's chunk800 FAISS index) ─────────────────────
embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
_vs = FAISS.load_local(str(CHUNK_CACHE / "chunk800.faiss"), embed_fn,
                       allow_dangerous_deserialization=True)

# Track how many times the agent calls the tool, and with what queries
TOOL_CALLS = []

@tool
def search_book(query: str) -> str:
    """Search the full text of 'The Great Gatsby' for passages relevant to the
    query. Returns the most relevant excerpts. Call this whenever you need
    evidence from the book. You may call it multiple times with different
    queries if your first search does not find what you need."""
    TOOL_CALLS.append(query)
    docs = _vs.similarity_search(query, k=4)
    return "\n\n---\n\n".join(d.page_content for d in docs)

llm = ChatGroq(model=GROQ_MODEL, temperature=0)

AGENT_SYSTEM = (
    "You are an expert on 'The Great Gatsby'. Use the search_book tool to find "
    "evidence before answering. If a search comes back without the answer, try "
    "REFORMULATING your query with different, more concrete vocabulary (e.g. "
    "character names, physical events) and search again. Answer based on what "
    "you find; you may draw reasonable inferences from the text, but do not "
    "invent facts. If the book truly does not cover it, say so."
)
agent = create_react_agent(llm, tools=[search_book], prompt=AGENT_SYSTEM)

# ── Passive RAG baseline (fixed single retrieval + inference prompt) ───────────
PASSIVE_PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. Answer based on the context below. "
    "You MAY draw reasonable logical inferences, but do NOT introduce facts the "
    "context gives no basis for. If the context gives no basis, say: "
    "'The provided context does not answer this question.'\n\n"
    "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
)
def passive_answer(question):
    docs = _vs.similarity_search(question, k=4)
    ctx = "\n\n---\n\n".join(d.page_content for d in docs)
    chain = PASSIVE_PROMPT | llm | StrOutputParser()
    return call(lambda: chain.invoke({"context": ctx, "question": question}))

def call(fn):
    while True:
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("429","RESOURCE_EXHAUSTED","503","UNAVAILABLE",
                                       "rate_limit","Rate limit")):
                print("    rate limit — waiting 20s..."); time.sleep(20)
            else: raise

QUESTIONS = [
    "How does Gatsby die?",                                  # vocab-gap (agent should reformulate)
    "Compare how Gatsby and Tom each treat Daisy.",          # multi-hop (needs 2 retrievals)
    "Who is Nick Carraway and how does he know Gatsby?",     # was thin in passive RAG
]

def run_agent(question):
    global TOOL_CALLS
    TOOL_CALLS = []
    result = call(lambda: agent.invoke({"messages": [("user", question)]}))
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = " ".join(p.get("text","") for p in final if isinstance(p, dict))
    return final, list(TOOL_CALLS)

def run():
    cache = pickle.loads(ANS_CACHE.read_bytes()) if ANS_CACHE.exists() else {}
    results = []
    for q in QUESTIONS:
        print(f"\n{'='*64}\nQ: {q}\n{'='*64}")
        if q in cache:
            e = cache[q]
            print(f"  [cache] agent tool-calls: {len(e['tool_calls'])}")
        else:
            print("  -- PASSIVE --")
            passive = passive_answer(q)
            print("  -- AGENTIC --")
            agentic, tool_calls = run_agent(q)
            e = {"q": q, "passive": passive, "agentic": agentic, "tool_calls": tool_calls}
            cache[q] = e
            ANS_CACHE.write_bytes(pickle.dumps(cache))
            print(f"  agent made {len(tool_calls)} tool call(s): {tool_calls}")
        results.append(e)
    return results

def write_report(results):
    path = Path(__file__).parent / "agentic_report.md"
    L = ["# Day 3 · Experiment 7 — Agentic RAG vs Passive RAG\n"]
    L.append("**Passive:** fixed single top-4 retrieval + inference prompt  ")
    L.append("**Agentic:** LLM with a `search_book` tool it can call repeatedly, "
             "reformulating queries as needed  \n")

    L.append("## Tool-Use Summary\n")
    L.append("| Question | Agent tool calls | Queries the agent chose |")
    L.append("|---|---|---|")
    for r in results:
        tcs = r["tool_calls"]
        qlist = "; ".join(f'"{t[:40]}"' for t in tcs) or "—"
        L.append(f"| {r['q'][:40]} | {len(tcs)} | {qlist} |")

    L.append("\n## Passive vs Agentic Answers\n")
    for r in results:
        L.append(f"### {r['q']}\n")
        L.append(f"**Agent tool calls ({len(r['tool_calls'])}):** "
                 f"{r['tool_calls']}\n")
        L.append(f"**PASSIVE:**\n> {r['passive'][:700]}\n")
        L.append(f"**AGENTIC:**\n> {r['agentic'][:700]}\n")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    results = run()
    write_report(results)
