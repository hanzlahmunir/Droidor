"""
Custom Agentic RAG with LangGraph + Gemini
Pattern based on: https://docs.langchain.com/oss/python/langgraph/agentic-rag
Embeddings: gemini-embedding-001 via Gemini API
LLM: gemini-flash-latest via langchain-google-genai
"""

import os
from typing import TypedDict, List, Annotated, Literal
from functools import lru_cache
import operator

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import StateGraph, END

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("GOOGLE_API_KEY")  # set via environment / .env, never hardcode
os.environ["GOOGLE_API_KEY"] = API_KEY

llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


# ── Sample documents (swap for your own source) ───────────────────────────────
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


@lru_cache(maxsize=1)
def _get_retriever():
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = splitter.create_documents(SAMPLE_DOCS)
    vectorstore = InMemoryVectorStore.from_documents(docs, embedding=embeddings)
    return vectorstore.as_retriever(search_kwargs={"k": 3})


# ── Graph state ───────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question: str
    retrieved_docs: List[Document]
    answer: str
    messages: Annotated[List, operator.add]


# ── Nodes ─────────────────────────────────────────────────────────────────────
def retrieve(state: AgentState) -> AgentState:
    docs = _get_retriever().invoke(state["question"])
    return {"retrieved_docs": docs}


def generate(state: AgentState) -> AgentState:
    context = "\n\n".join(d.page_content for d in state["retrieved_docs"])
    prompt = (
        f"Answer the question using ONLY the context below. "
        f"If the context doesn't contain the answer, say so.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {state['question']}\n\nAnswer:"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content
    if isinstance(content, list):
        answer = " ".join(p["text"] for p in content if isinstance(p, dict) and "text" in p)
    else:
        answer = content
    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
    }


def grade_docs(state: AgentState) -> Literal["generate", "no_docs"]:
    return "generate" if state["retrieved_docs"] else "no_docs"


def no_docs_fallback(state: AgentState) -> AgentState:
    answer = "I couldn't find relevant information to answer that question."
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


# ── Build graph ───────────────────────────────────────────────────────────────
def build_rag_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("no_docs", no_docs_fallback)

    graph.set_entry_point("retrieve")
    graph.add_conditional_edges(
        "retrieve",
        grade_docs,
        {"generate": "generate", "no_docs": "no_docs"},
    )
    graph.add_edge("generate", END)
    graph.add_edge("no_docs", END)
    return graph.compile()


rag_agent = build_rag_graph()


# ── Public helper ─────────────────────────────────────────────────────────────
def ask(question: str) -> str:
    result = rag_agent.invoke({
        "question": question,
        "retrieved_docs": [],
        "answer": "",
        "messages": [HumanMessage(content=question)],
    })
    return result["answer"]


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    questions = [
        "What is LangGraph?",
        "How does RAG reduce hallucinations?",
        "What is InMemoryVectorStore used for?",
        "Tell me about Gemini 1.5 Flash.",
        "What is the capital of France?",  # out-of-context — tests fallback
    ]
    for q in questions:
        print(f"\nQ: {q}")
        print(f"A: {ask(q)}")
