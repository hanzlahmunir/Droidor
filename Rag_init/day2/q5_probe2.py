"""
Q5 Probe 2 — Does allowing INFERENCE fix the refusal?
------------------------------------------------------
Same full death-scene context that Probe 1 refused on.
We vary ONLY the prompt guardrail wording:

  STRICT   — original: "ONLY the context, do NOT use prior knowledge"
             (this refused in Probe 1 even on the full scene)
  INFERENCE — allows drawing logical conclusions from the context,
              still forbids outside facts.

If STRICT refuses but INFERENCE answers on the SAME context, we've
proven the failure was the guardrail suppressing reasoning, not
retrieval and not missing information.

Run: python q5_probe2.py
"""

import os, time
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

API_KEY = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)

QUESTION = "How does Gatsby die?"

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

STRICT = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer using ONLY the context below. "
    "If the context does not contain enough information to answer, say exactly: "
    "'The provided context does not answer this question.' "
    "Do NOT use your prior knowledge.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

INFERENCE = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby'. "
    "Answer based on the context below. You MAY draw reasonable logical "
    "inferences from what the context states, even if it is not spelled out "
    "word-for-word — but do NOT introduce facts that the context gives no "
    "basis for. If the context truly gives no basis for an answer, say: "
    "'The provided context does not answer this question.'\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

def ask(prompt):
    chain = prompt | llm | StrOutputParser()
    while True:
        try:
            return chain.invoke({"context": FULL_SCENE, "question": QUESTION})
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                print("    rate limit — waiting 65s...")
                time.sleep(65)
            else:
                raise

if __name__ == "__main__":
    print(f"QUESTION: {QUESTION}")
    print("CONTEXT: full death scene (identical for both)\n")
    for label, prompt in [("STRICT guardrail", STRICT),
                          ("INFERENCE-allowed guardrail", INFERENCE)]:
        print(f"{'='*64}\n{label}\n{'='*64}")
        answer = ask(prompt)
        refused = "does not answer" in answer.lower()
        print(f"[{'REFUSED' if refused else 'ANSWERED'}]\n{answer}\n")
