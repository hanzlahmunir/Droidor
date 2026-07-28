"""
Q5 Probe — Is "How does Gatsby die?" a retrieval failure or a source ambiguity?
-------------------------------------------------------------------------------
Force-feeds the LLM hand-picked context and asks how Gatsby dies.
If the LLM refuses even with the PERFECT passage, the problem is the
source text / prompt guardrail, not retrieval.

Three conditions:
  A. FULL SCENE   — the complete death passage (lines 5720-5761), which
                    DOES contain "heard the shots", the pool, the red
                    circle, and Wilson's body. A human can infer the murder.
  B. FRAGMENT     — only the ambiguous tail (red circle + Wilson's body),
                    NO "shots" — mimics what a single retrieved chunk holds.
  C. SCATTERED    — the 4 chunks the semantic retriever actually returned
                    in Exp 3 (none contain the death) — reproduces the failure.

Run: python q5_probe.py
"""

import os, time
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

API_KEY = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

PROMPT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer using ONLY the context below. "
    "If the context does not contain enough information to answer, say exactly: "
    "'The provided context does not answer this question.' "
    "Do NOT use your prior knowledge.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)
chain = PROMPT | llm | StrOutputParser()

QUESTION = "How does Gatsby die?"

# ── A. FULL SCENE (contains "heard the shots") ────────────────────────────────
FULL_SCENE = """\
Gatsby shouldered the mattress and started for the pool. Once he
stopped and shifted it a little, and the chauffeur asked him if he
needed help, but he shook his head and in a moment disappeared among
the yellowing trees.

The chauffeur—he was one of Wolfshiem's protégés—heard the
shots—afterwards he could only say that he hadn't thought anything
much about them. I drove from the station directly to Gatsby's house
and my rushing anxiously up the front steps was the first thing that
alarmed anyone. With scarcely a word said, four of us, the chauffeur,
butler, gardener, and I hurried down to the pool.

With little ripples that were hardly the shadows of waves, the laden
mattress moved irregularly down the pool. The touch of a cluster of
leaves revolved it slowly, tracing a thin red circle in the water.

It was after we started with Gatsby toward the house that the gardener
saw Wilson's body a little way off in the grass, and the holocaust was
complete."""

# ── B. FRAGMENT (ambiguous tail only — no "shots") ────────────────────────────
FRAGMENT = """\
With little ripples that were hardly the shadows of waves, the laden
mattress moved irregularly down the pool. A small gust of wind that
scarcely corrugated the surface was enough to disturb its accidental
course with its accidental burden. The touch of a cluster of leaves
revolved it slowly, tracing, like the leg of transit, a thin red
circle in the water.

It was after we started with Gatsby toward the house that the gardener
saw Wilson's body a little way off in the grass, and the holocaust was
complete."""

# ── C. SCATTERED (what semantic retrieval actually returned in Exp 3) ─────────
SCATTERED = """\
A dim background started to take shape behind him, but at her next
remark it faded away. "However, I don't believe it."

---

It was Gatsby's father, a solemn old man, very helpless and dismayed,
bundled up in a long cheap ulster against the warm September day.

---

heightened sensitivity to the promises of life, as if he were related
to one of those intricate machines that register earthquakes.

---

"I don't think so," she said innocently. "Why?" We went in. To my
overwhelming surprise the living-room was deserted."""

CONDITIONS = [
    ("A. FULL SCENE (has 'heard the shots')", FULL_SCENE),
    ("B. FRAGMENT (ambiguous tail, no 'shots')", FRAGMENT),
    ("C. SCATTERED (actual Exp 3 retrieval)", SCATTERED),
]

def ask(context):
    while True:
        try:
            return chain.invoke({"context": context, "question": QUESTION})
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                print("    rate limit — waiting 65s...")
                time.sleep(65)
            else:
                raise

if __name__ == "__main__":
    print(f"QUESTION: {QUESTION}\n")
    for label, ctx in CONDITIONS:
        print(f"{'='*64}")
        print(label)
        print('='*64)
        answer = ask(ctx)
        refused = "does not answer" in answer.lower()
        verdict = "REFUSED" if refused else "ANSWERED"
        print(f"[{verdict}]\n{answer}\n")
