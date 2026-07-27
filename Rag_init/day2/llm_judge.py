"""
Experiment 4 — LLM-as-Judge (replacing the brittle keyword scorer)
-------------------------------------------------------------------
Our keyword scorer lied: it flagged an 83% answer as REFUSED because the
text contained "not explicitly". This experiment grades cached answers with
a second LLM call that scores two independent axes:

  FAITHFULNESS  (1-5) — is every claim in the answer supported by the
                        retrieved context? (catches hallucination)
  COMPLETENESS  (1-5) — does the answer actually address the question using
                        what the context offers? (catches lazy refusals)

We grade the INFERENCE-prompt answers from prompt_compare (the config we're
keeping going forward) and compare the judge's verdict to the keyword score,
to see where keyword matching was wrong.

Judge calls are cached (judge.cache.pkl) — resume-safe, ~5 calls total.
Report: day2/judge_report.md
Run:    python llm_judge.py
"""

import os, time, json, pickle, re
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

API_KEY = "AQ.Ab8RN6KYb9ZmoBn91Rj_GE6Eo31GqMDkOJHSi0fLiAqUblajUw"  # key 4 (live)
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH    = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR    = Path(__file__).parent / "chunk_cache"
INF_CACHE    = Path(__file__).parent / "prompt_compare.answers.pkl"
JUDGE_CACHE  = Path(__file__).parent / "judge.cache.pkl"

EMBED_MODEL   = "all-MiniLM-L6-v2"
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 80
FAISS_KEY     = "chunk800"
K             = 4

# Keyword scores from prompt_compare (inference column) for side-by-side
KEYWORD_SCORES = {
    "Who is Jay Gatsby and what is his dream?": "83%",
    "What does the green light symbolize?": "100%",
    "Describe the relationship between Gatsby and Daisy.": "60%",
    "Who is Nick Carraway and how does he know Gatsby?": "20%",
    "How does Gatsby die?": "REFUSED",
}

judge_llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

JUDGE_PROMPT = ChatPromptTemplate.from_template(
    "You are a strict evaluator of a RAG system's answer. You are given the "
    "CONTEXT that was retrieved, the QUESTION, and the ANSWER the system gave.\n\n"
    "Score two axes from 1 to 5:\n"
    "FAITHFULNESS: 5 = every claim is directly supported by or reasonably "
    "inferable from the CONTEXT; 1 = the answer invents facts not in the CONTEXT.\n"
    "COMPLETENESS: 5 = fully answers the QUESTION using what the CONTEXT allows; "
    "1 = refuses or ignores answerable information present in the CONTEXT. "
    "(If the CONTEXT genuinely lacks the answer, a correct refusal should still "
    "score 5 on FAITHFULNESS and 3 on COMPLETENESS — it did the right thing.)\n\n"
    "Respond with ONLY a JSON object, no prose:\n"
    '{{"faithfulness": <1-5>, "completeness": <1-5>, '
    '"reason": "<one sentence>"}}\n\n'
    "CONTEXT:\n{context}\n\n"
    "QUESTION: {question}\n\n"
    "ANSWER: {answer}\n\nJSON:"
)
judge_chain = JUDGE_PROMPT | judge_llm | StrOutputParser()

def load_raw():
    raw = BOOK_PATH.read_text(encoding="utf-8")
    s = raw.find("*** START OF THE PROJECT GUTENBERG")
    e = raw.find("*** END OF THE PROJECT GUTENBERG")
    if s != -1: raw = raw[raw.find("\n", s) + 1:]
    if e != -1: raw = raw[:e]
    return raw

def parse_judge(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"faithfulness": None, "completeness": None, "reason": "parse-failed: " + text[:100]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"faithfulness": None, "completeness": None, "reason": "json-error: " + m.group(0)[:100]}

def judge(context, question, answer):
    while True:
        try:
            raw = judge_chain.invoke({"context": context, "question": question, "answer": answer})
            return parse_judge(raw)
        except Exception as e:
            if any(x in str(e) for x in ("429","RESOURCE_EXHAUSTED","503","UNAVAILABLE")):
                print("    rate limit — waiting 65s..."); time.sleep(65)
            else:
                raise

def run():
    # Rebuild the exact retriever used for the inference answers so the judge
    # sees the SAME context the answer was generated from.
    raw = load_raw()
    RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP).create_documents([raw])
    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    vs = FAISS.load_local(str(CACHE_DIR / f"{FAISS_KEY}.faiss"), embed_fn,
                          allow_dangerous_deserialization=True)
    retriever = vs.as_retriever(search_kwargs={"k": K})
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)

    inf = pickle.loads(INF_CACHE.read_bytes())
    cache = pickle.loads(JUDGE_CACHE.read_bytes()) if JUDGE_CACHE.exists() else {}

    results = []
    for e in inf:
        q, a = e["q"], e["a"]
        if q in cache:
            verdict = cache[q]
            print(f"  [cache] F={verdict['faithfulness']} C={verdict['completeness']}  {q[:45]}")
        else:
            ctx = fmt(retriever.invoke(q))
            verdict = judge(ctx, q, a)
            cache[q] = verdict
            JUDGE_CACHE.write_bytes(pickle.dumps(cache))
            print(f"  F={verdict['faithfulness']} C={verdict['completeness']}  {q[:45]}")
        results.append({"q": q, "a": a, "keyword": KEYWORD_SCORES.get(q, "?"), "judge": verdict})
    return results

def write_report(results):
    path = Path(__file__).parent / "judge_report.md"
    L = ["# Experiment 4 — LLM-as-Judge vs Keyword Scorer\n"]
    L.append("**Answers graded:** inference-prompt config "
             "(all-MiniLM-L6-v2, chunk=800, k=4, semantic)  ")
    L.append("**Judge:** gemini-flash-latest, scoring Faithfulness & Completeness (1-5)  \n")

    L.append("## Keyword Score vs Judge Verdict\n")
    L.append("| Question | Keyword | Faithfulness | Completeness | Judge's reason |")
    L.append("|---|---|---|---|---|")
    for r in results:
        j = r["judge"]
        L.append(f"| {r['q'][:40]} | {r['keyword']} | {j['faithfulness']}/5 "
                 f"| {j['completeness']}/5 | {j.get('reason','')[:80]} |")

    L.append("\n## Where Keyword Scoring and the Judge Disagree\n")
    for r in results:
        j = r["judge"]
        kw = r["keyword"]
        note = ""
        if kw == "REFUSED" and j["completeness"] and j["completeness"] >= 3:
            note = "Judge says the refusal was appropriate (context lacked the answer)."
        elif kw != "REFUSED":
            pct = int(kw.rstrip("%"))
            if j["completeness"] and pct < 40 and j["completeness"] >= 4:
                note = "Keyword UNDERRATED — judge found it complete despite few keyword hits."
            elif j["completeness"] and pct >= 80 and j["completeness"] <= 2:
                note = "Keyword OVERRATED — keywords present but judge found it incomplete."
        if note:
            L.append(f"- **{r['q'][:50]}** (kw={kw}, F={j['faithfulness']}, "
                     f"C={j['completeness']}): {note}")

    L.append("\n## Full Answers + Judge Reasoning\n")
    for r in results:
        j = r["judge"]
        L.append(f"### {r['q']}\n")
        L.append(f"- Keyword score: **{r['keyword']}**")
        L.append(f"- Judge: **Faithfulness {j['faithfulness']}/5, "
                 f"Completeness {j['completeness']}/5**")
        L.append(f"- Judge reason: {j.get('reason','')}")
        L.append(f"\n> {r['a'][:700]}\n")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    results = run()
    write_report(results)
