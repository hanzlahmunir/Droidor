"""Neo4j graph store adapter.

Retrieval here is graph-native, which is the point of offering Neo4j alongside
Chroma: we full-text search Product nodes, then *expand along relationships*
(same Category, and ALSO_BOUGHT neighbors) so the context includes related
products a pure vector store wouldn't surface. Falls back gracefully if the
graph is empty.

Requires the graph to be populated: `python ingest.py --stores neo4j`, with
Neo4j running (`docker compose up -d`).
"""
from __future__ import annotations

import threading

from langchain_core.documents import Document

from stores.base import Store, StructuredResult

_FULLTEXT_INDEX = "product_text_ft"


_graph_lock = threading.Lock()
_graph_singleton = None


def _graph():
    """Return one shared Neo4jGraph, built exactly once even under the thread pool.

    Concurrent first-time construction otherwise races both on the connection and
    on the full-text index creation (Aura's IF NOT EXISTS isn't atomic against a
    simultaneous create -> EquivalentSchemaRuleAlreadyExists).
    """
    global _graph_singleton
    if _graph_singleton is not None:
        return _graph_singleton
    with _graph_lock:
        if _graph_singleton is None:
            from neo4j_conn import get_neo4j_graph

            graph = get_neo4j_graph()
            try:
                graph.query(
                    f"CREATE FULLTEXT INDEX {_FULLTEXT_INDEX} IF NOT EXISTS "
                    "FOR (p:Product) ON EACH [p.title, p.text]"
                )
            except Exception as exc:  # tolerate a concurrent/pre-existing create
                if "already exists" not in str(exc).lower():
                    raise
            _graph_singleton = graph
    return _graph_singleton


def _lucene_escape(query: str) -> str:
    """Make a free-text query safe for Lucene, as a loose OR of terms."""
    special = set('+-&|!(){}[]^"~*?:\\/')
    terms = []
    for tok in query.split():
        cleaned = "".join(ch for ch in tok if ch not in special)
        if cleaned:
            terms.append(cleaned)
    return " OR ".join(terms) if terms else query


class Neo4jStore(Store):
    name = "neo4j"

    def __init__(self) -> None:
        self._g = _graph()

    def retrieve(self, query: str, k: int) -> list[Document]:
        # Seed with full-text hits, then expand along graph relationships. We
        # take fewer seeds and let neighbors fill k, so results carry graph
        # context (related/also-bought products), not just text matches.
        seed_k = max(1, k // 2)
        rows = self._g.query(
            f"""
            CALL db.index.fulltext.queryNodes('{_FULLTEXT_INDEX}', $q)
            YIELD node AS p, score
            WITH p, score ORDER BY score DESC LIMIT $seed_k
            OPTIONAL MATCH (p)-[:ALSO_BOUGHT]->(nbr:Product)
            OPTIONAL MATCH (p)-[:IN_CATEGORY]->(:Category)<-[:IN_CATEGORY]-(sib:Product)
            WITH p, score,
                 collect(DISTINCT nbr)[..2] AS nbrs,
                 collect(DISTINCT sib)[..2] AS sibs
            RETURN p.parent_asin AS asin, p.title AS title, p.text AS text,
                   score,
                   [x IN nbrs | x.title] AS also_bought,
                   [x IN sibs | x.title] AS related
            """,
            {"q": _lucene_escape(query), "seed_k": seed_k},
        )

        docs: list[Document] = []
        seen: set[str] = set()
        for r in rows:
            if r["asin"] in seen:
                continue
            seen.add(r["asin"])
            content = r.get("text") or r.get("title") or ""
            extras = []
            if r.get("also_bought"):
                extras.append("Also bought: " + ", ".join(filter(None, r["also_bought"])))
            if r.get("related"):
                extras.append("Related: " + ", ".join(filter(None, r["related"])))
            if extras:
                content = content + "\n" + "\n".join(extras)
            docs.append(
                Document(
                    page_content=content,
                    metadata={
                        "parent_asin": r["asin"],
                        "title": r.get("title"),
                        "score": r.get("score"),
                        "source": "neo4j",
                    },
                )
            )
            if len(docs) >= k:
                break
        return docs

    def structured_query(self, spec: dict) -> StructuredResult:
        """Compile the filter spec to Cypher and let Neo4j aggregate natively.

        Unlike the Chroma path (filter in DB, sort/count in Python), Neo4j does
        the count/sort/limit itself in one query — the graph store's strength for
        aggregation. We build parameterized Cypher (no string interpolation of
        values) so it's safe.
        """
        where_parts: list[str] = []
        params: dict = {}
        if "price_min" in spec:
            where_parts.append("p.price >= $price_min")
            params["price_min"] = spec["price_min"]
        if "price_max" in spec:
            where_parts.append("p.price <= $price_max")
            params["price_max"] = spec["price_max"]
        if "rating_min" in spec:
            where_parts.append("p.rating >= $rating_min")
            params["rating_min"] = spec["rating_min"]
        if "store" in spec:
            where_parts.append("EXISTS { (p)-[:SOLD_BY]->(s:Store) WHERE s.name = $store }")
            params["store"] = spec["store"]
        if "category" in spec:
            where_parts.append("EXISTS { (p)-[:IN_CATEGORY]->(c:Category) WHERE c.name = $category }")
            params["category"] = spec["category"]

        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        if spec.get("op") == "count":
            cypher = f"MATCH (p:Product) {where} RETURN count(p) AS n"
            rows = self._g.query(cypher, params)
            n = rows[0]["n"] if rows else 0
            return StructuredResult(op="count", count=n, query=cypher)

        order = ""
        sort = spec.get("sort")
        if sort == "price_asc":
            order = "ORDER BY p.price ASC"
        elif sort == "price_desc":
            order = "ORDER BY p.price DESC"
        elif sort == "rating_desc":
            order = "ORDER BY p.rating DESC"
        limit = spec.get("limit", 20)
        params["lim"] = limit

        cypher = (
            f"MATCH (p:Product) {where} "
            f"RETURN p.title AS title, p.price AS price, p.rating AS average_rating "
            f"{order} LIMIT $lim"
        )
        rows = self._g.query(cypher, params)
        # Also compute the total matching count so 'list' answers can say "showing N of M".
        count_rows = self._g.query(f"MATCH (p:Product) {where} RETURN count(p) AS n", params)
        total = count_rows[0]["n"] if count_rows else len(rows)
        return StructuredResult(op="list", rows=rows, count=total, query=cypher)
