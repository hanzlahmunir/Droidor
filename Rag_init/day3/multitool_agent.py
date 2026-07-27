"""
Day 3 · Experiment 8 — Multi-Step, Multi-Tool Agent
----------------------------------------------------
Experiment 7 gave the agent ONE tool (search_book). This gives it a TOOLBOX
and tests whether it selects the RIGHT tool per task — including tasks that
semantic retrieval fundamentally CANNOT do (like counting exact occurrences).

Tools:
  - search_book(query)          semantic search (Exp 7's tool)
  - count_mentions(term)        EXACT count of a term in the full text
                                (retrieval can't count — needs a real function)
  - get_excerpt_around(phrase)  find a literal phrase + surrounding context
  - list_characters()           return the main characters

Test questions are chosen so the RIGHT answer requires the RIGHT tool:
  Q1 counting     -> must use count_mentions, not search_book
  Q2 quote lookup -> must use get_excerpt_around
  Q3 multi-step   -> count + search combined
  Q4 roster       -> list_characters

We log which tools the agent chose, in order, to see if it routes correctly.

Model: Groq llama-3.3-70b. Report: day3/multitool_report.md
Run:   python multitool_agent.py
"""

import os, re, time, pickle
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

os.environ["GROQ_API_KEY"] = "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"
# gpt-oss-120b has more reliable OpenAI-style tool-calling than llama-3.3,
# which intermittently emits malformed <function=...> syntax that Groq rejects.
GROQ_MODEL = "openai/gpt-oss-120b"

BOOK_PATH   = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CHUNK_CACHE = Path(__file__).parent.parent / "day2" / "chunk_cache"
ANS_CACHE   = Path(__file__).parent / "multitool.cache.pkl"
EMBED_MODEL = "all-MiniLM-L6-v2"

# ── Full book text (for exact-count / excerpt tools) ──────────────────────────
def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    s = raw.find("*** START OF THE PROJECT GUTENBERG")
    e = raw.find("*** END OF THE PROJECT GUTENBERG")
    if s != -1: raw = raw[raw.find("\n", s) + 1:]
    if e != -1: raw = raw[:e]
    return raw
BOOK = load_raw()

embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
vs = FAISS.load_local(str(CHUNK_CACHE / "chunk800.faiss"), embed_fn,
                      allow_dangerous_deserialization=True)

# ── Tool-call log ─────────────────────────────────────────────────────────────
TOOL_LOG = []

@tool
def search_book(query: str) -> str:
    """Semantically search 'The Great Gatsby' for passages relevant to a query.
    Use for open-ended questions about plot, characters, themes, or meaning.
    Returns the most relevant excerpts."""
    TOOL_LOG.append(("search_book", query))
    docs = vs.similarity_search(query, k=4)
    return "\n\n---\n\n".join(d.page_content for d in docs)

@tool
def count_mentions(term: str) -> str:
    """Count exactly how many times a word or phrase appears in the full text
    of 'The Great Gatsby'. Use this for any 'how many times' / 'how often'
    question — semantic search cannot count, but this can."""
    TOOL_LOG.append(("count_mentions", term))
    n = len(re.findall(re.escape(term), BOOK, flags=re.IGNORECASE))
    return f'The term "{term}" appears {n} times in the novel.'

@tool
def get_excerpt_around(phrase: str) -> str:
    """Find a literal phrase in the book and return it with ~300 characters of
    surrounding context. Use when asked about a specific quote or exact wording."""
    TOOL_LOG.append(("get_excerpt_around", phrase))
    idx = BOOK.lower().find(phrase.lower())
    if idx == -1:
        return f'The phrase "{phrase}" was not found verbatim in the text.'
    start = max(0, idx - 300); end = min(len(BOOK), idx + len(phrase) + 300)
    return "..." + BOOK[start:end].strip() + "..."

@tool
def list_characters() -> str:
    """Return the list of main characters in 'The Great Gatsby'. Use when asked
    who the characters are or for a character roster."""
    TOOL_LOG.append(("list_characters", ""))
    return ("Main characters: Nick Carraway (narrator), Jay Gatsby, "
            "Daisy Buchanan, Tom Buchanan, Jordan Baker, Myrtle Wilson, "
            "George Wilson, Meyer Wolfshiem.")

TOOLS = [search_book, count_mentions, get_excerpt_around, list_characters]

llm = ChatGroq(model=GROQ_MODEL, temperature=0)
SYSTEM = (
    "You are an expert research assistant for 'The Great Gatsby'. You have "
    "several tools. Think about WHICH tool fits the question:\n"
    "- Counting occurrences -> count_mentions (never estimate counts yourself).\n"
    "- A specific quote or exact wording -> get_excerpt_around.\n"
    "- Who the characters are -> list_characters.\n"
    "- Open-ended meaning/plot/theme -> search_book.\n"
    "You may call multiple tools. Base your answer on tool results; do not "
    "invent facts. Give a concise final answer."
)
agent = create_react_agent(llm, tools=TOOLS, prompt=SYSTEM)

def call(fn, max_tool_retries=3):
    tool_retries = 0
    while True:
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("429","rate_limit","Rate limit","503")):
                print("    rate limit — waiting 20s..."); time.sleep(20)
            elif "tool_use_failed" in msg and tool_retries < max_tool_retries:
                # Model emitted malformed tool syntax; retry the step.
                tool_retries += 1
                print(f"    malformed tool call — retry {tool_retries}...")
                time.sleep(2)
            else: raise

QUESTIONS = [
    "How many times is the green light mentioned in the book?",      # count
    "What is the exact wording around 'so we beat on, boats'?",      # excerpt
    "Who are the main characters, and how many times is Gatsby named?",  # multi-tool
    "How many times does the word 'money' appear?",                  # count
]

def run_one(q):
    global TOOL_LOG
    TOOL_LOG = []
    result = call(lambda: agent.invoke({"messages": [("user", q)]}))
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = " ".join(p.get("text","") for p in final if isinstance(p, dict))
    return final, list(TOOL_LOG)

def run():
    cache = pickle.loads(ANS_CACHE.read_bytes()) if ANS_CACHE.exists() else {}
    results = []
    for q in QUESTIONS:
        print(f"\n{'='*64}\nQ: {q}\n{'='*64}")
        if q in cache:
            e = cache[q]
            print(f"  [cache] tools: {[t[0] for t in e['tools']]}")
        else:
            answer, tools = run_one(q)
            e = {"q": q, "answer": answer, "tools": tools}
            cache[q] = e
            ANS_CACHE.write_bytes(pickle.dumps(cache))
            print(f"  tools used: {[t[0] for t in tools]}")
            print(f"  answer: {answer[:120]}")
        results.append(e)
    return results

def write_report(results):
    path = Path(__file__).parent / "multitool_report.md"
    L = ["# Day 3 · Experiment 8 — Multi-Tool Agent\n"]
    L.append("Agent has 4 tools; we test whether it routes each question to the "
             "RIGHT one (esp. counting, which retrieval cannot do).\n")
    L.append("## Tool Routing\n")
    L.append("| Question | Tools chosen (in order) |")
    L.append("|---|---|")
    for r in results:
        seq = " -> ".join(f"{t[0]}({t[1][:20]})" if t[1] else t[0] for t in r["tools"])
        L.append(f"| {r['q'][:45]} | {seq or '—'} |")

    L.append("\n## Answers\n")
    for r in results:
        L.append(f"### {r['q']}\n")
        L.append(f"**Tools:** {[t[0] for t in r['tools']]}\n")
        L.append(f"> {r['answer'][:600]}\n")

    L.append("\n## Takeaway\n")
    L.append("- The agent must recognize that **counting** questions need "
             "`count_mentions`, not `search_book` — retrieval returns relevant "
             "chunks but cannot produce an exact count. Correct routing here is "
             "the core test of multi-tool reasoning.")
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    results = run()
    write_report(results)
