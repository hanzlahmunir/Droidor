"""Chroma vector store adapter.

Loads the persisted collection built by ``ingest.py`` and exposes similarity
search through the common :class:`Store` interface. Uses the same embedding
model as ingestion (via ``embeddings.get_embeddings``) — mismatching them
silently breaks retrieval.
"""
from __future__ import annotations

import threading

from langchain_core.documents import Document

from config import CHROMA_COLLECTION, CHROMA_DIR
from embeddings import get_embeddings
from stores.base import Store, StructuredResult

# The persistent Chroma client is process-wide and must be built exactly once,
# even under the runner's thread pool — concurrent first-time construction races
# on the SQLite tenant and errors ("Could not connect to tenant default_tenant").
# A lock + single shared instance makes it safe and cheap to reuse across windows.
_db_lock = threading.Lock()
_db = None


def _load_collection():
    global _db
    if _db is not None:
        return _db
    with _db_lock:
        if _db is None:
            from langchain_chroma import Chroma

            if not CHROMA_DIR.exists():
                raise RuntimeError(
                    f"Chroma collection not found at {CHROMA_DIR}. "
                    "Run: python ingest.py --limit 2000 --stores chroma"
                )
            _db = Chroma(
                collection_name=CHROMA_COLLECTION,
                embedding_function=get_embeddings(),
                persist_directory=str(CHROMA_DIR),
            )
    return _db


class ChromaStore(Store):
    name = "chroma"

    def __init__(self) -> None:
        self._db = _load_collection()

    def retrieve(self, query: str, k: int) -> list[Document]:
        return self._db.similarity_search(query, k=k)

    def structured_query(self, spec: dict) -> StructuredResult:
        """Compile the filter spec to a Chroma metadata `where` and scan ALL rows.

        Note: Chroma can filter on metadata but can't range-filter price *and*
        sort server-side, so we pull the matching metadatas and finish the
        sort/limit/count in Python. This runs over the whole collection, not a
        top-k window — which is the point.
        """
        where = _build_where(spec)
        coll = self._db._collection
        got = coll.get(where=where or None, include=["metadatas"])
        metas = got.get("metadatas") or []

        rows = [
            {
                "title": m.get("title"),
                "price": m.get("price"),
                "store": m.get("store"),
                "category": m.get("category"),
                "average_rating": m.get("average_rating"),
            }
            for m in metas
        ]

        sort = spec.get("sort")
        if sort == "price_asc":
            rows = sorted((r for r in rows if r["price"] is not None), key=lambda r: r["price"])
        elif sort == "price_desc":
            rows = sorted((r for r in rows if r["price"] is not None), key=lambda r: r["price"], reverse=True)
        elif sort == "rating_desc":
            rows = sorted((r for r in rows if r["average_rating"] is not None), key=lambda r: r["average_rating"], reverse=True)

        human = f"Chroma where={where or '{}'}"
        if spec.get("op") == "count":
            return StructuredResult(op="count", count=len(rows), query=human)

        limit = spec.get("limit", 20)
        return StructuredResult(op="list", rows=rows[:limit], count=len(rows), query=human)


def _build_where(spec: dict) -> dict:
    """Translate a filter spec into a Chroma `where` clause.

    Chroma requires multiple conditions under an explicit $and. Price ranges use
    $gte/$lte. String fields (store/category) match exactly; if the exact match
    misses, the LLM-summarize step still explains the (empty) result honestly.
    """
    conds: list[dict] = []
    if "price_min" in spec:
        conds.append({"price": {"$gte": spec["price_min"]}})
    if "price_max" in spec:
        conds.append({"price": {"$lte": spec["price_max"]}})
    if "rating_min" in spec:
        conds.append({"average_rating": {"$gte": spec["rating_min"]}})
    if "store" in spec:
        conds.append({"store": spec["store"]})
    if "category" in spec:
        conds.append({"category": spec["category"]})

    if not conds:
        return {}
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}
