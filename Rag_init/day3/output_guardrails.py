"""
Day 3 · Experiment 10 — Output Guardrails
------------------------------------------
Input guardrails (Exp 9) stop bad questions getting IN. Output guardrails stop
bad answers getting OUT. We test two output-side defenses:

  1. CITATION ENFORCEMENT — require the answer to cite which chunk(s) it used;
     reject/flag any answer with no citation.
  2. GROUNDEDNESS CHECK — after answering, verify (cheaply) that the answer's
     claims are actually supported by the retrieved context, catching the case
     where the LLM ignored the context and answered from training data.

We deliberately include a question whose answer is NOT in the retrieved context
to see if the guardrail catches an ungrounded (training-data) answer.

Model: Groq gpt-oss-120b. Report: day3/output_guardrails_report.md
Run:   python output_guardrails.py
"""

import os, re, time, pickle
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

os.environ["GROQ_API_KEY"] = "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"
GROQ_MODEL = "openai/gpt-oss-120b"

CHUNK_CACHE = Path(__file__).parent.parent / "day2" / "chunk_cache"
ANS_CACHE   = Path(__file__).parent / "output_guardrails.cache.pkl"
EMBED_MODEL = "all-MiniLM-L6-v2"

embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
vs = FAISS.load_local(str(CHUNK_CACHE / "chunk800.faiss"), embed_fn,
                      allow_dangerous_deserialization=True)
llm = ChatGroq(model=GROQ_MODEL, temperature=0)

def call(fn):
    while True:
        try: return fn()
        except Exception as e:
            if any(x in str(e) for x in ("429","rate_limit","Rate limit","503")):
                print("    rate limit — waiting 20s..."); time.sleep(20)
            else: raise

# ── Answer prompt that REQUIRES citations ─────────────────────────────────────
CITE_PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. Answer using ONLY the numbered "
    "context passages below. After EACH claim, cite the passage number(s) you "
    "used in square brackets, e.g. [1] or [2,3]. If the passages do not support "
    "an answer, say 'The provided context does not answer this question.'\n\n"
    "{numbered_context}\n\nQuestion: {question}\n\nAnswer (with [n] citations):"
)

# ── Groundedness judge (cheap post-hoc check) ─────────────────────────────────
GROUND_PROMPT = ChatPromptTemplate.from_template(
    "Given the CONTEXT and an ANSWER, decide if EVERY factual claim in the "
    "answer is supported by the context. Reply with exactly one word: "
    "GROUNDED (all claims supported) or UNGROUNDED (contains unsupported "
    "claims / used outside knowledge).\n\n"
    "CONTEXT:\n{context}\n\nANSWER:\n{answer}\n\nVerdict:"
)

def numbered(docs):
    return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs))

def has_citation(answer):
    return bool(re.search(r"\[\d+(?:\s*,\s*\d+)*\]", answer))

QUESTIONS = [
    "What does the green light symbolize?",           # answerable, grounded
    "Describe the relationship between Gatsby and Daisy.",  # answerable
    "What year did World War 2 end?",                 # NOT in book — trap for ungrounded
    "How does Gatsby die?",                           # not retrievable — should refuse
]

def run():
    cache = pickle.loads(ANS_CACHE.read_bytes()) if ANS_CACHE.exists() else {}
    results = []
    for q in QUESTIONS:
        print(f"\n{'='*60}\nQ: {q}\n{'='*60}")
        if q in cache:
            e = cache[q]
            print(f"  [cache] cited={e['cited']} grounded={e['grounded']} refused={e['refused']}")
        else:
            docs = vs.similarity_search(q, k=4)
            ctx = "\n\n---\n\n".join(d.page_content for d in docs)
            nctx = numbered(docs)
            answer = call(lambda: (CITE_PROMPT | llm | StrOutputParser())
                          .invoke({"numbered_context": nctx, "question": q}))
            cited = has_citation(answer)
            refused = "does not answer this question" in answer.lower() and len(answer) < 200
            verdict = call(lambda: (GROUND_PROMPT | llm | StrOutputParser())
                           .invoke({"context": ctx, "answer": answer})).strip().upper()
            grounded = verdict.startswith("GROUNDED")
            e = {"q": q, "answer": answer, "cited": cited,
                 "grounded": grounded, "refused": refused}
            cache[q] = e
            ANS_CACHE.write_bytes(pickle.dumps(cache))
            print(f"  cited={cited}  grounded={grounded}  refused={refused}")
            print("  answer: " + answer[:120].encode("ascii", "replace").decode())
        results.append(e)
    return results

def write_report(results):
    path = Path(__file__).parent / "output_guardrails_report.md"
    L = ["# Day 3 · Experiment 10 — Output Guardrails\n"]
    L.append("Two output-side defenses: **citation enforcement** (every claim "
             "cites a passage) and a **groundedness check** (a judge verifies "
             "claims are supported by context, catching training-data leakage).\n")
    L.append("| Question | Cited? | Grounded? | Refused? | Note |")
    L.append("|---|---|---|---|---|")
    for r in results:
        note = ""
        if "World War 2" in r["q"]:
            note = "trap: not in book — should refuse or be flagged ungrounded"
        elif r["q"].startswith("How does Gatsby die"):
            note = "not retrievable — should refuse"
        L.append(f"| {r['q'][:40]} | {'yes' if r['cited'] else 'NO'} "
                 f"| {'yes' if r['grounded'] else 'NO'} "
                 f"| {'yes' if r['refused'] else 'no'} | {note} |")

    L.append("\n## Full Answers\n")
    for r in results:
        L.append(f"### {r['q']}\n")
        L.append(f"- cited={r['cited']}  grounded={r['grounded']}  refused={r['refused']}\n")
        L.append(f"> {r['answer'][:600]}\n")

    L.append("\n## Takeaway\n")
    L.append("- **Citation enforcement** makes answers auditable — a reader can "
             "verify each claim against the cited passage. Answers without "
             "citations are a red flag.")
    L.append("- **Groundedness check** catches the dangerous case: the LLM "
             "ignoring context and answering from training data. The WW2 trap "
             "question tests exactly this — a well-behaved system either refuses "
             "or gets flagged UNGROUNDED.")
    L.append("- Together: input guards (Exp 9) + output guards (Exp 10) = "
             "end-to-end safety envelope around the RAG core.")
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    results = run()
    write_report(results)
