"""
RAG with plain LangChain LCEL (no LangGraph)
Same Gemini stack as lg_rag.py but using a simple retrieval chain via pipes.
"""

import os
from langchain.chat_models import init_chat_model
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = "AQ.Ab8RN6L5WoVoHIRxxx3h4PdsTuub41-kMGg_ZKZ3tdbanzhN9A"
os.environ["GOOGLE_API_KEY"] = API_KEY

llm = init_chat_model("gemini-flash-latest", model_provider="google_genai", temperature=0)
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

# ── Sample documents ──────────────────────────────────────────────────────────
SAMPLE_DOCS = [
    "LangGraph is a library for building stateful, multi-actor applications with LLMs. "
    "It extends LangChain with support for cyclic graphs, persistence, and human-in-the-loop.",
    "RAG (Retrieval-Augmented Generation) combines retrieval with generation to ground LLM "
    "answers in real documents, reducing hallucinations.",
    "Gemini is Google's family of multimodal AI models. Gemini 1.5 Flash is a fast, efficient "
    "model suitable for high-throughput tasks.",
    "FAISS (Facebook AI Similarity Search) is a library for efficient similarity search over "
    "dense vectors at scale.",
    "LangChain provides composable building blocks for LLM applications including chains, "
    "agents, retrievers, and memory.",
    "InMemoryVectorStore is a simple in-process vectorstore that needs no external database, "
    "useful for prototyping and testing RAG pipelines.",
]

# ── Build vectorstore + retriever ─────────────────────────────────────────────
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
docs = splitter.create_documents(SAMPLE_DOCS)
vectorstore = InMemoryVectorStore.from_documents(docs, embedding=embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# ── Prompt ────────────────────────────────────────────────────────────────────
prompt = ChatPromptTemplate.from_template(
    "Answer the question using ONLY the context below. "
    "If the context doesn't contain the answer, say so.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\nAnswer:"
)

# ── Chain (LCEL pipe syntax) ──────────────────────────────────────────────────
def format_docs(docs):
    return "\n\n".join(d.page_content for d in docs)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

# ── Helper ────────────────────────────────────────────────────────────────────
def ask(question: str) -> str:
    return rag_chain.invoke(question)

# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    questions = [
        "What is LangGraph?",
        "How does RAG reduce hallucinations?",
        "What is InMemoryVectorStore used for?",
        "Tell me about Gemini 1.5 Flash.",
        "What is the capital of France?",
    ]
    for q in questions:
        print(f"\nQ: {q}")
        print(f"A: {ask(q)}")
