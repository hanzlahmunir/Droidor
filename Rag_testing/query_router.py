"""Query router: decide how to answer a question, then build the right query.

Two routes:
  - SEMANTIC  ("find me a fun co-op board game")  -> vector top-k retrieval
  - STRUCTURED ("how many products cost $100-200") -> a real query over the
    WHOLE dataset (Chroma metadata filter or Neo4j Cypher), because counting /
    filtering / min-max are database operations that top-k retrieval cannot do.

The route is chosen by a cheap LLM classifier. For the structured route, an LLM
translates the question into a store-specific query (text-to-query), which the
store executes over all records.
"""
from __future__ import annotations

import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# --------------------------------------------------------------------------- #
# Route classification
# --------------------------------------------------------------------------- #
_ROUTE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Classify a shopping question as either 'structured' or 'semantic'.\n"
            "- 'structured': asks to COUNT, FILTER, or rank by a concrete attribute "
            "(price, brand/store, category, rating) over the whole catalog — e.g. "
            "'how many products are $100-200', 'list items under $20', "
            "'cheapest board game', 'products by LEGO'.\n"
            "- 'semantic': asks to FIND or RECOMMEND products by description/meaning — "
            "e.g. 'a fun co-op game for kids', 'something educational for toddlers'.\n"
            "Answer with exactly one word: structured or semantic.",
        ),
        ("human", "{question}"),
    ]
)


def classify_route(question: str, llm) -> str:
    """Return 'structured' or 'semantic' for the question."""
    chain = _ROUTE_PROMPT | llm | StrOutputParser()
    verdict = chain.invoke({"question": question}).strip().lower()
    return "structured" if "structured" in verdict else "semantic"


# --------------------------------------------------------------------------- #
# Structured filter extraction (store-agnostic intermediate representation)
# --------------------------------------------------------------------------- #
# We first extract a small, safe JSON "filter spec" from the question. Each store
# then compiles that spec to its own query language. This keeps the LLM from
# emitting raw executable queries (safer) while still being fully general over
# the attributes we support.
_FILTER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Extract a JSON filter spec from a shopping question about a product "
            "catalog. Available fields: price (number, USD), store (brand string), "
            "category (string), average_rating (number 0-5).\n"
            "Return ONLY JSON with this shape (omit keys that don't apply):\n"
            "{{\n"
            '  "op": "count" | "list",\n'
            '  "price_min": <number>, "price_max": <number>,\n'
            '  "store": "<brand>", "category": "<text>",\n'
            '  "rating_min": <number>,\n'
            '  "sort": "price_asc" | "price_desc" | "rating_desc",\n'
            '  "limit": <int>\n'
            "}}\n"
            "Examples:\n"
            "'how many products are between $100 and $200' -> "
            '{{"op":"count","price_min":100,"price_max":200}}\n'
            "'the 5 cheapest items' -> "
            '{{"op":"list","sort":"price_asc","limit":5}}\n'
            "'list toys under $20 with rating above 4' -> "
            '{{"op":"list","price_max":20,"rating_min":4}}',
        ),
        ("human", "{question}"),
    ]
)


def extract_filter(question: str, llm) -> dict:
    """LLM -> a validated filter spec dict. Raises ValueError on unparseable output."""
    chain = _FILTER_PROMPT | llm | StrOutputParser()
    raw = chain.invoke({"question": question}).strip()
    spec = _parse_json(raw)

    clean: dict = {}
    clean["op"] = "count" if spec.get("op") == "count" else "list"
    for num_key in ("price_min", "price_max", "rating_min"):
        if isinstance(spec.get(num_key), (int, float)):
            clean[num_key] = float(spec[num_key])
    for str_key in ("store", "category"):
        if isinstance(spec.get(str_key), str) and spec[str_key].strip():
            clean[str_key] = spec[str_key].strip()
    if spec.get("sort") in ("price_asc", "price_desc", "rating_desc"):
        clean["sort"] = spec["sort"]
    if isinstance(spec.get("limit"), int) and spec["limit"] > 0:
        clean["limit"] = min(spec["limit"], 50)
    return clean


def _parse_json(raw: str) -> dict:
    """Extract a JSON object from possibly-fenced LLM output."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in LLM output: {raw[:120]!r}")
    return json.loads(match.group(0))


# --------------------------------------------------------------------------- #
# Structured answer: run the DB query, then have the LLM phrase the real result
# --------------------------------------------------------------------------- #
_SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a shopping assistant. You ran a database query over the FULL "
            "product catalog and got exact results below. Answer the user's question "
            "using ONLY these results. State counts exactly. If the result is empty, "
            "say no matching products were found.",
        ),
        ("human", "Question: {question}\n\nQuery results:\n{results}"),
    ]
)


def _render_results(result) -> str:
    """Turn a StructuredResult into text for the summarizer LLM."""
    if result.op == "count":
        return f"Exact count of matching products: {result.count}"
    lines = [f"Total matching products: {result.count}", "Showing:"]
    for r in result.rows:
        price = f"${r['price']:.2f}" if r.get("price") is not None else "price n/a"
        rating = r.get("average_rating")
        rating_s = f", rating {rating}" if rating is not None else ""
        lines.append(f"- {r.get('title', '(untitled)')} ({price}{rating_s})")
    if not result.rows:
        lines.append("(none)")
    return "\n".join(lines)


def run_structured(question: str, store, llm) -> tuple[str, list, list[str]]:
    """Execute the structured route end-to-end.

    Returns (answer, source_rows_as_docs, steps). Raises NotImplementedError if
    the store has no structured support (caller falls back to semantic).
    """
    from langchain_core.documents import Document
    from langchain_core.output_parsers import StrOutputParser

    steps = ["route -> structured"]
    spec = extract_filter(question, llm)
    steps.append(f"filter spec -> {spec}")

    result = store.structured_query(spec)  # may raise NotImplementedError
    steps.append(f"query [{store.name}] -> {result.query}")
    steps.append(
        f"result -> count={result.count}"
        + (f", {len(result.rows)} rows" if result.op == "list" else "")
    )

    chain = _SUMMARIZE_PROMPT | llm | StrOutputParser()
    answer = chain.invoke(
        {"question": question, "results": _render_results(result)}
    ).strip()

    # Surface listed products as "sources" for the UI's sources expander.
    docs = [
        Document(page_content=r.get("title", ""), metadata=r)
        for r in result.rows
    ]
    return answer, docs, steps
