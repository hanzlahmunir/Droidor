"""Store abstraction: a uniform retrieval interface over Chroma and Neo4j.

Frameworks (LangChain/LangGraph) depend only on this interface, so swapping the
data store is a config change, not a code change. Adding a new store = one new
subclass here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from langchain_core.documents import Document


@dataclass
class StructuredResult:
    """Result of a structured query over the whole dataset.

    ``count`` is set for count queries; ``rows`` holds listed products. ``query``
    is the store-specific query we actually ran (shown in the trace so you can
    see what 'ask anything' compiled to).
    """

    op: str                       # "count" | "list"
    count: int | None = None
    rows: list[dict] = field(default_factory=list)
    query: str = ""               # human-readable form of the executed query


class Store(ABC):
    """Uniform retrieval surface for a backing data store."""

    name: str

    @abstractmethod
    def retrieve(self, query: str, k: int) -> list[Document]:
        """Return up to ``k`` relevant documents for ``query``."""

    def structured_query(self, spec: dict) -> StructuredResult:
        """Run a count/list/filter query over the WHOLE dataset from a filter spec.

        Default raises so stores opt in explicitly. ``spec`` is the validated
        dict from ``query_router.extract_filter``.
        """
        raise NotImplementedError(f"{self.name} does not support structured queries")

    def as_retriever(self, k: int):
        """Adapt to a LangChain Runnable retriever (query str -> list[Document])."""
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(lambda q: self.retrieve(q, k))


def get_store(name: str) -> Store:
    """Factory: build a Store by name ('chroma' | 'neo4j')."""
    if name == "chroma":
        from stores.chroma_store import ChromaStore

        return ChromaStore()
    if name == "neo4j":
        from stores.neo4j_store import Neo4jStore

        return Neo4jStore()
    raise ValueError(f"Unknown store: {name!r}")
