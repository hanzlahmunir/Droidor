"""
Prompt Comparison — Strict vs Inference guardrail on the SAME retrieval
-----------------------------------------------------------------------
Isolates the effect of the generation guardrail, holding retrieval fixed
at the best config from Exp 1-3:
    embedding = all-MiniLM-L6-v2, chunk_size=800, k=4, semantic (FAISS)

For each of the 5 questions we now have:
  - STRICT answer   — loaded from Exp 3 cache (semantic_only.answers.pkl)
  - INFERENCE answer — generated fresh with the loosened prompt

Only 5 new API calls. Report: day2/prompt_compare_report.md
Run: python prompt_compare.py
"""

import os, time, pickle
from pathlib import Path
from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

API_KEY = "AQ.Ab8RN6KYb9ZmoBn91Rj_GE6Eo31GqMDkOJHSi0fLiAqUblajUw"  # key 4 (live)
os.environ["GOOGLE_API_KEY"] = API_KEY

BOOK_PATH  = Path(__file__).parent.parent / "day1" / "gatsby.txt"
CACHE_DIR  = Path(__file__).parent / "chunk_cache"
STRICT_CACHE = Path(__file__).parent / "hybrid_cache" / "semantic_only.answers.pkl"
ANS_CACHE  = Path(__file__).parent / "prompt_compare.answers.pkl"

EMBED_MODEL   = "all-MiniLM-L6-v2"
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 80
FAISS_KEY     = "chunk800"
K             = 4

QUESTIONS = [
    "Who is Jay Gatsby and what is his dream?",
    "What does the green light symbolize?",
    "Describe the relationship between Gatsby and Daisy.",
    "Who is Nick Carraway and how does he know Gatsby?",
    "How does Gatsby die?",
]

ANSWER_FACTS = {
    "Who is Jay Gatsby and what is his dream?": [
        "platonic", "self", "dream", "daisy", "west egg", "rich"],
    "What does the green light symbolize?": [
        "green", "daisy", "future", "dream", "dock"],
    "Describe the relationship between Gatsby and Daisy.": [
        "love", "affair", "tom", "married", "reunion"],
    "Who is Nick Carraway and how does he know Gatsby?": [
        "narrator", "neighbor", "west egg", "cousin", "bond"],
    "How does Gatsby die?": [
        "wilson", "shot", "pool", "myrtle", "murder"],
}

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

INFERENCE_PROMPT = ChatPromptTemplate.from_template(
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

def score(question, answer):
    facts = ANSWER_FACTS.get(question, [])
    al = answer.lower()
    hits = [f for f in facts if f in al]
    # A REAL refusal is short and dominated by the canonical refusal sentence.
    # A long answer that merely contains "not explicitly" in passing is NOT a
    # refusal — that was a scorer bug that understated the inference prompt.
    canonical = "the provided context does not answer this question"
    stripped = al.strip().rstrip(".")
    refused = (
        stripped == canonical                       # exact refusal
        or (len(answer) < 250 and canonical in al)  # short + refusal phrase
    )
    return {
        "score_pct": round(100 * len(hits) / len(facts)) if facts else 0,
        "facts_found": hits, "refused": refused,
    }

def run():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    raw = load_raw()
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP).create_documents([raw])
    embed_fn = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    vs = FAISS.load_local(str(CACHE_DIR / f"{FAISS_KEY}.faiss"), embed_fn,
                          allow_dangerous_deserialization=True)
    retriever = vs.as_retriever(search_kwargs={"k": K})
    fmt = lambda docs: "\n\n---\n\n".join(d.page_content for d in docs)
    chain = ({"context": retriever | fmt, "question": RunnablePassthrough()}
             | INFERENCE_PROMPT | llm | StrOutputParser())

    # Load strict answers from Exp 3 semantic cache, RE-SCORED with the fixed
    # refusal logic so both columns use the same (corrected) scorer.
    strict = {}
    if STRICT_CACHE.exists():
        for e in pickle.loads(STRICT_CACHE.read_bytes()):
            e = dict(e)
            e["score"] = score(e["q"], e["a"])
            strict[e["q"]] = e
        print(f"Loaded {len(strict)} strict answers from Exp 3 cache\n")

    # Resume inference answers; re-score from stored text with fixed logic
    inf = pickle.loads(ANS_CACHE.read_bytes()) if ANS_CACHE.exists() else []
    for e in inf:
        e["score"] = score(e["q"], e["a"])
    done = {e["q"] for e in inf}

    for q in QUESTIONS:
        if q in done:
            e = next(x for x in inf if x["q"] == q)
            s = e["score"]
            print(f"  [cache] [{'REFUSED' if s['refused'] else str(s['score_pct'])+'%'}] {q[:50]}")
            continue
        while True:
            try:
                answer = chain.invoke(q); break
            except Exception as ex:
                if any(x in str(ex) for x in ("429","RESOURCE_EXHAUSTED","503","UNAVAILABLE")):
                    print("    rate limit — waiting 65s..."); time.sleep(65)
                else: raise
        s = score(q, answer)
        inf.append({"q": q, "a": answer, "score": s})
        ANS_CACHE.write_bytes(pickle.dumps(inf))
        print(f"  [{'REFUSED' if s['refused'] else str(s['score_pct'])+'%'}] {q[:50]}")

    return strict, {e["q"]: e for e in inf}

def write_report(strict, inf):
    path = Path(__file__).parent / "prompt_compare_report.md"
    L = ["# Prompt Comparison — Strict vs Inference Guardrail\n"]
    L.append("**Retrieval (identical for both):** all-MiniLM-L6-v2, "
             "chunk=800, k=4, semantic FAISS  ")
    L.append("**Only variable:** the generation prompt's grounding instruction  \n")

    L.append("## Score Comparison\n")
    L.append("| Question | STRICT | INFERENCE | Change |")
    L.append("|---|---|---|---|")
    s_ref = i_ref = 0
    s_sum = i_sum = 0
    for q in QUESTIONS:
        se = strict.get(q); ie = inf.get(q)
        s_tag = "—"; i_tag = "—"
        if se:
            ss = se["score"]
            s_tag = "REFUSED" if ss["refused"] else f"{ss['score_pct']}%"
            if ss["refused"]: s_ref += 1
            s_sum += 0 if ss["refused"] else ss["score_pct"]
        if ie:
            iss = ie["score"]
            i_tag = "REFUSED" if iss["refused"] else f"{iss['score_pct']}%"
            if iss["refused"]: i_ref += 1
            i_sum += 0 if iss["refused"] else iss["score_pct"]
        change = ""
        if se and ie:
            if se["score"]["refused"] and not ie["score"]["refused"]:
                change = "✅ REFUSED → ANSWERED"
            elif not se["score"]["refused"] and not ie["score"]["refused"]:
                d = ie["score"]["score_pct"] - se["score"]["score_pct"]
                change = f"{'+' if d>=0 else ''}{d}%"
            elif se["score"]["refused"] and ie["score"]["refused"]:
                change = "still refused"
        L.append(f"| {q[:48]} | {s_tag} | {i_tag} | {change} |")

    L.append(f"\n**Refusals:** STRICT {s_ref}/5 → INFERENCE {i_ref}/5  ")
    L.append(f"**Avg score (counting refusals as 0):** "
             f"STRICT {s_sum/5:.0f}% → INFERENCE {i_sum/5:.0f}%  \n")

    L.append("## Full Answers\n")
    for q in QUESTIONS:
        L.append(f"### {q}\n")
        se = strict.get(q); ie = inf.get(q)
        if se:
            st = "REFUSED" if se["score"]["refused"] else f"{se['score']['score_pct']}%"
            L.append(f"**STRICT ({st}):**\n> {se['a'][:600]}\n")
        if ie:
            it = "REFUSED" if ie["score"]["refused"] else f"{ie['score']['score_pct']}%"
            L.append(f"**INFERENCE ({it}):**\n> {ie['a'][:600]}\n")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport saved -> {path}")

if __name__ == "__main__":
    strict, inf = run()
    write_report(strict, inf)
