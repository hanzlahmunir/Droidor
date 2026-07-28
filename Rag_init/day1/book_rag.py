"""
Book RAG — The Great Gatsby (F. Scott Fitzgerald)
LangChain LCEL + Gemini embeddings + gemini-flash-latest
"""

import os
import time
from langchain.chat_models import init_chat_model
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

# ── Load book ─────────────────────────────────────────────────────────────────
BOOK_PATH = os.path.join(os.path.dirname(__file__), "gatsby.txt")

with open(BOOK_PATH, "r", encoding="utf-8") as f:
    raw_text = f.read()

# Strip Project Gutenberg header/footer (content between START and END markers)
start = raw_text.find("*** START OF THE PROJECT GUTENBERG")
end = raw_text.find("*** END OF THE PROJECT GUTENBERG")
if start != -1:
    raw_text = raw_text[raw_text.find("\n", start) + 1 :]
if end != -1:
    raw_text = raw_text[:end]

print(f"Book loaded: {len(raw_text):,} characters")

# ── Chunk + embed ─────────────────────────────────────────────────────────────
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.create_documents([raw_text])
print(f"Chunks created: {len(chunks)}")

# Embed in batches of 80 with retry to stay under 100 req/min rate limit
BATCH_SIZE = 80
vectorstore = InMemoryVectorStore(embedding=embeddings)
for i in range(0, len(chunks), BATCH_SIZE):
    batch = chunks[i : i + BATCH_SIZE]
    while True:
        try:
            vectorstore.add_documents(batch)
            print(f"  Embedded chunks {i+1}–{min(i+BATCH_SIZE, len(chunks))} / {len(chunks)}")
            break
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                print("  Rate limit hit, waiting 60s...")
                time.sleep(60)
            elif "ReadTimeout" in msg or "10060" in msg or "connection" in msg.lower():
                print("  Network timeout, retrying in 10s...")
                time.sleep(10)
            else:
                raise

retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
print("Vectorstore ready.\n")

# ── Prompt ────────────────────────────────────────────────────────────────────
prompt = ChatPromptTemplate.from_template(
    "You are an expert on 'The Great Gatsby' by F. Scott Fitzgerald. "
    "Answer the question using ONLY the context passages below. "
    "If the context doesn't contain enough information, say so.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

# ── Chain ─────────────────────────────────────────────────────────────────────
def format_docs(docs):
    return "\n\n---\n\n".join(d.page_content for d in docs)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

def ask(question: str) -> str:
    return rag_chain.invoke(question)

# ── Test questions ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    questions = [
        "Who is Jay Gatsby and what is his dream?",
        "What does the green light symbolize?",
        "Describe the relationship between Gatsby and Daisy.",
        "Who is Nick Carraway and how does he know Gatsby?",
        "How does Gatsby die?",
    ]
    for q in questions:
        print(f"Q: {q}")
        print(f"A: {ask(q)}")
        print()
