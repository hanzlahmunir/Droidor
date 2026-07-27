"""LangChain (LCEL) RAG adapter.

A classic retrieve -> format -> prompt -> llm chain. Effort scales retrieval
depth (``k``) and, above a threshold, adds an LLM query-rewrite prepass that
turns the user's question into a keyword-rich retrieval query (a lesson from
the prior study: fluent questions often miss idiosyncratic catalog vocabulary).
"""
from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import EffortSettings
from frameworks.base import SYSTEM_PROMPT, RagFramework, RagResult, format_docs
from query_router import classify_route, run_structured
from stores.base import Store

_REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Rewrite the user's question into a concise keyword search query for "
            "a product catalog. Return ONLY the query text, no punctuation or quotes.",
        ),
        ("human", "{question}"),
    ]
)

_ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "Product context:\n{context}\n\nQuestion: {question}"),
    ]
)


class LangChainRag(RagFramework):
    name = "langchain"

    def run(self, query: str, store: Store, llm, settings: EffortSettings) -> RagResult:
        steps = []

        # Route: structured (count/filter over the whole dataset) vs semantic.
        if classify_route(query, llm) == "structured":
            try:
                answer, docs, s_steps = run_structured(query, store, llm)
                return RagResult(answer=answer, sources=docs, steps=s_steps)
            except NotImplementedError:
                steps.append("structured unsupported here -> semantic fallback")
            except Exception as exc:  # bad spec / query error -> fall back
                steps.append(f"structured failed ({type(exc).__name__}) -> semantic")

        search_query = query
        if settings.rewrite_query:
            rewrite_chain = _REWRITE_PROMPT | llm | StrOutputParser()
            search_query = rewrite_chain.invoke({"question": query}).strip() or query
            steps.append(f"rewrite -> {search_query!r}")

        docs = store.retrieve(search_query, k=settings.k)
        steps.append(f"retrieve k={settings.k} -> {len(docs)} docs")

        answer_chain = _ANSWER_PROMPT | llm | StrOutputParser()
        answer = answer_chain.invoke(
            {"context": format_docs(docs), "question": query}
        )
        steps.append("generate")

        return RagResult(answer=answer.strip(), sources=docs, steps=steps)
