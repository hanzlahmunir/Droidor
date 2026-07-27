"""Offline ingestion: Amazon Reviews 2023 (Video Games metadata) -> Chroma + Neo4j.

Run once (or to top up). Idempotent: Chroma upserts by product id, Neo4j uses
MERGE, so re-running with a larger --limit just adds more.

Usage:
    python ingest.py --limit 2000 --stores chroma
    python ingest.py --limit 2000 --stores chroma,neo4j
    python ingest.py --limit 500                     # both stores, small sample

Dataset: McAuley-Lab/Amazon-Reviews-2023, config raw_meta_Video_Games.
Product doc text = title + description + features; metadata carries the
structured fields used for filtering and for building the graph.
"""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from config import (
    CHROMA_COLLECTION,
    CHROMA_DIR,
    HF_DATASET,
    HF_META_CONFIG,
    HF_PARQUET_SHARDS,
)
from embeddings import get_embeddings

load_dotenv()


# --------------------------------------------------------------------------- #
# Dataset -> normalized product records
# --------------------------------------------------------------------------- #
def _clean_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v]


def _product_text(rec: dict) -> str:
    """Build the embeddable text for a product from its metadata."""
    parts = [rec.get("title") or ""]
    desc = " ".join(_clean_list(rec.get("description")))
    if desc:
        parts.append(desc)
    feats = _clean_list(rec.get("features"))
    if feats:
        parts.append("Features: " + " ".join(feats))
    return "\n".join(p for p in parts if p).strip()


def _first_category(rec: dict) -> str:
    cats = _clean_list(rec.get("categories"))
    return cats[-1] if cats else (rec.get("main_category") or "Unknown")


def load_products(limit: int):
    """Yield normalized product dicts from the HF parquet shards (streaming).

    The dataset's loader script is blocked by newer `datasets`, so we read the
    parquet files directly. We stream shard-by-shard and stop once `limit` valid
    products are collected, so a small sample only touches shard 0.
    """
    from datasets import load_dataset

    ds = load_dataset(
        "parquet",
        data_files={"full": HF_PARQUET_SHARDS},
        split="full",
        streaming=True,
    )
    count = 0
    for rec in ds:
        asin = rec.get("parent_asin")
        title = rec.get("title")
        if not asin or not title:
            continue
        text = _product_text(rec)
        if not text:
            continue

        price = rec.get("price")
        try:
            price = float(price) if price not in (None, "", "None") else None
        except (ValueError, TypeError):
            price = None

        yield {
            "parent_asin": asin,
            "title": title,
            "text": text,
            "store": (rec.get("store") or "Unknown").strip() or "Unknown",
            "category": _first_category(rec),
            "price": price,
            "average_rating": rec.get("average_rating"),
            "rating_number": rec.get("rating_number"),
            "bought_together": _clean_list(rec.get("bought_together")),
        }
        count += 1
        if count >= limit:
            break


# --------------------------------------------------------------------------- #
# Chroma
# --------------------------------------------------------------------------- #
def ingest_chroma(products: list[dict]) -> None:
    from langchain_chroma import Chroma
    from langchain_core.documents import Document

    print(f"[chroma] embedding + indexing {len(products)} products ...")
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    store = Chroma(
        collection_name=CHROMA_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(CHROMA_DIR),
    )

    docs, ids = [], []
    for p in products:
        meta = {
            "parent_asin": p["parent_asin"],
            "title": p["title"],
            "store": p["store"],
            "category": p["category"],
        }
        if p["price"] is not None:
            meta["price"] = p["price"]
        if p["average_rating"] is not None:
            meta["average_rating"] = p["average_rating"]
        docs.append(Document(page_content=p["text"], metadata=meta))
        ids.append(p["parent_asin"])  # stable id => upsert on re-run

    # Batch to keep memory + request sizes reasonable.
    B = 256
    for i in range(0, len(docs), B):
        store.add_documents(docs[i : i + B], ids=ids[i : i + B])
        print(f"[chroma]   {min(i + B, len(docs))}/{len(docs)}")
    print(f"[chroma] done -> {CHROMA_DIR}")


# --------------------------------------------------------------------------- #
# Neo4j
# --------------------------------------------------------------------------- #
def ingest_neo4j(products: list[dict]) -> None:
    from neo4j_conn import get_neo4j_graph

    print(f"[neo4j] connecting to {os.getenv('NEO4J_URI')} ...")
    graph = get_neo4j_graph()

    # Constraints make MERGE fast and idempotent.
    graph.query(
        "CREATE CONSTRAINT product_asin IF NOT EXISTS "
        "FOR (p:Product) REQUIRE p.parent_asin IS UNIQUE"
    )
    graph.query(
        "CREATE CONSTRAINT store_name IF NOT EXISTS "
        "FOR (s:Store) REQUIRE s.name IS UNIQUE"
    )
    graph.query(
        "CREATE CONSTRAINT category_name IF NOT EXISTS "
        "FOR (c:Category) REQUIRE c.name IS UNIQUE"
    )

    rows = [
        {
            "asin": p["parent_asin"],
            "title": p["title"],
            "text": p["text"][:4000],
            "price": p["price"],
            "rating": p["average_rating"],
            "store": p["store"],
            "category": p["category"],
            "also": p["bought_together"],
        }
        for p in products
    ]

    print(f"[neo4j] MERGE {len(rows)} products + relationships ...")
    graph.query(
        """
        UNWIND $rows AS row
        MERGE (p:Product {parent_asin: row.asin})
          SET p.title = row.title,
              p.text = row.text,
              p.price = row.price,
              p.rating = row.rating
        MERGE (s:Store {name: row.store})
        MERGE (p)-[:SOLD_BY]->(s)
        MERGE (c:Category {name: row.category})
        MERGE (p)-[:IN_CATEGORY]->(c)
        WITH p, row
        UNWIND row.also AS other_asin
          MERGE (o:Product {parent_asin: other_asin})
          MERGE (p)-[:ALSO_BOUGHT]->(o)
        """,
        {"rows": rows},
    )
    print("[neo4j] done.")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Amazon Video Games into RAG stores.")
    ap.add_argument("--limit", type=int, default=2000, help="max products to ingest")
    ap.add_argument(
        "--stores",
        default="chroma",
        help="comma-separated: chroma,neo4j (default: chroma)",
    )
    args = ap.parse_args()
    targets = {s.strip() for s in args.stores.split(",") if s.strip()}

    print(f"Loading up to {args.limit} products from {HF_DATASET}/{HF_META_CONFIG} ...")
    products = list(load_products(args.limit))
    print(f"Loaded {len(products)} products.")

    if "chroma" in targets:
        ingest_chroma(products)
    if "neo4j" in targets:
        ingest_neo4j(products)
    print("Ingestion complete.")


if __name__ == "__main__":
    main()
