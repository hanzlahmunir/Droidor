"""Q5 — INFERENCE-allowed guardrail only, on key 4. Single request."""
import os, time
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# GOOGLE_API_KEY must be set via environment / .env — never hardcode a key here.
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

chain = INFERENCE | llm | StrOutputParser()
while True:
    try:
        answer = chain.invoke({"context": FULL_SCENE, "question": QUESTION})
        break
    except Exception as e:
        if any(x in str(e) for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
            print("    rate limit — waiting 65s..."); time.sleep(65)
        else:
            raise

refused = "does not answer" in answer.lower()
print(f"[{'REFUSED' if refused else 'ANSWERED'}]")
print(answer)
