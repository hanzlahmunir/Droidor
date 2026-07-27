"""Framework abstraction: run one RAG pipeline and return a uniform result.

Each orchestration framework (LangChain, LangGraph, ...) is one subclass. They
all take the same inputs (query, store, llm, effort settings) and return the
same :class:`RagResult`, so the runner and UI treat them interchangeably.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from langchain_core.documents import Document

from config import EffortSettings
from stores.base import Store


@dataclass
class RagResult:
    """Uniform output of any pipeline run."""

    answer: str
    sources: list[Document] = field(default_factory=list)
    latency_s: float = 0.0
    tokens: int | None = None
    cost: float | None = None
    steps: list[str] = field(default_factory=list)  # trace of what the pipeline did
    error: str | None = None


# Shared prompt: reason FROM the retrieved context, don't import outside facts.
# (Lesson carried over from the prior study's prompt root-cause finding.)
SYSTEM_PROMPT = (
    "You are a shopping assistant answering questions about products in a catalog. "
    "Use ONLY the retrieved product context to answer. You may make one-step "
    "inferences from it, but do not invent products, prices, or facts not supported "
    "by the context. If the context does not contain the answer, say so plainly. "
    "Cite product titles you rely on."
)


def format_docs(docs: list[Document]) -> str:
    """Render retrieved documents into a context block for the prompt."""
    if not docs:
        return "(no products retrieved)"
    blocks = []
    for i, d in enumerate(docs, 1):
        title = d.metadata.get("title", "")
        blocks.append(f"[{i}] {title}\n{d.page_content}")
    return "\n\n".join(blocks)


class RagFramework(ABC):
    """Base class for an orchestration framework adapter."""

    name: str

    @abstractmethod
    def run(
        self,
        query: str,
        store: Store,
        llm,
        settings: EffortSettings,
    ) -> RagResult:
        """Execute the pipeline and return a :class:`RagResult` (no metrics yet)."""


def get_framework(name: str) -> RagFramework:
    """Factory: build a RagFramework by name ('langchain' | 'langgraph')."""
    if name == "langchain":
        from frameworks.langchain_rag import LangChainRag

        return LangChainRag()
    if name == "langgraph":
        from frameworks.langgraph_rag import LangGraphRag

        return LangGraphRag()
    raise ValueError(f"Unknown framework: {name!r}")
