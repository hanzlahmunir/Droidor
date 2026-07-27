"""LangGraph RAG adapter.

A StateGraph whose shape grows with effort:
    (optional) rewrite -> retrieve -> (optional) grade -> [retry retrieve | generate]

Low effort is a plain retrieve->generate. Higher effort turns on a query
rewrite, then document grading: if retrieved docs look irrelevant, it
reformulates and retries retrieval up to ``max_retrieval_rounds`` before
answering. This is the "agentic search" idea from the prior study, expressed
as explicit graph nodes.
"""
from __future__ import annotations

from typing import TypedDict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph

from config import EffortSettings
from frameworks.base import SYSTEM_PROMPT, RagFramework, RagResult, format_docs
from query_router import classify_route, run_structured
from stores.base import Store


class _State(TypedDict, total=False):
    question: str
    search_query: str
    docs: list
    rounds: int
    answer: str
    steps: list


_REWRITE = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Rewrite the question into a keyword product-search query. If a previous "
            "query returned poor results, try different vocabulary. Return ONLY the query.",
        ),
        ("human", "Question: {question}\nPrevious query (if any): {prev}"),
    ]
)

_GRADE = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Do the retrieved products plausibly help answer the question? "
            "Answer with exactly 'yes' or 'no'.",
        ),
        ("human", "Question: {question}\n\nProducts:\n{context}"),
    ]
)

_ANSWER = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "Product context:\n{context}\n\nQuestion: {question}"),
    ]
)


class LangGraphRag(RagFramework):
    name = "langgraph"

    def run(self, query: str, store: Store, llm, settings: EffortSettings) -> RagResult:
        # Route: structured (count/filter over the whole dataset) vs semantic.
        if classify_route(query, llm) == "structured":
            try:
                answer, docs, s_steps = run_structured(query, store, llm)
                return RagResult(answer=answer, sources=docs, steps=s_steps)
            except NotImplementedError:
                pass  # store has no structured support -> semantic graph below
            except Exception:
                pass  # bad spec / query error -> semantic graph below

        rewrite_chain = _REWRITE | llm | StrOutputParser()
        grade_chain = _GRADE | llm | StrOutputParser()
        answer_chain = _ANSWER | llm | StrOutputParser()

        def rewrite(state: _State) -> _State:
            prev = state.get("search_query", "")
            q = rewrite_chain.invoke({"question": state["question"], "prev": prev}).strip()
            q = q or state["question"]
            return {"search_query": q, "steps": state["steps"] + [f"rewrite -> {q!r}"]}

        def retrieve(state: _State) -> _State:
            q = state.get("search_query") or state["question"]
            docs = store.retrieve(q, k=settings.k)
            rounds = state.get("rounds", 0) + 1
            return {
                "docs": docs,
                "rounds": rounds,
                "steps": state["steps"] + [f"retrieve#{rounds} k={settings.k} -> {len(docs)}"],
            }

        def grade(state: _State) -> _State:
            verdict = grade_chain.invoke(
                {"question": state["question"], "context": format_docs(state["docs"])}
            ).strip().lower()
            return {"steps": state["steps"] + [f"grade -> {verdict}"], "answer": verdict}

        def generate(state: _State) -> _State:
            ans = answer_chain.invoke(
                {"context": format_docs(state["docs"]), "question": state["question"]}
            )
            return {"answer": ans.strip(), "steps": state["steps"] + ["generate"]}

        # Route after grading: retry retrieval (via rewrite) if docs look bad and
        # we still have rounds left; otherwise answer.
        def after_grade(state: _State) -> str:
            good = state.get("answer", "").startswith("yes")
            if good or state.get("rounds", 1) >= settings.max_retrieval_rounds:
                return "generate"
            return "rewrite"

        g = StateGraph(_State)
        g.add_node("rewrite", rewrite)
        g.add_node("retrieve", retrieve)
        g.add_node("generate", generate)

        if settings.rewrite_query:
            g.set_entry_point("rewrite")
            g.add_edge("rewrite", "retrieve")
        else:
            g.set_entry_point("retrieve")

        if settings.grade_docs:
            g.add_node("grade", grade)
            g.add_edge("retrieve", "grade")
            g.add_conditional_edges(
                "grade", after_grade, {"rewrite": "rewrite", "generate": "generate"}
            )
        else:
            g.add_edge("retrieve", "generate")

        g.add_edge("generate", END)
        app = g.compile()

        # Each reform round is ~3 node visits (rewrite -> retrieve -> grade), so
        # scale the recursion budget to the allowed rounds (+ headroom) or the
        # graph aborts before using its full round budget.
        recursion_limit = settings.max_retrieval_rounds * 4 + 10
        final = app.invoke(
            {"question": query, "steps": [], "rounds": 0},
            {"recursion_limit": recursion_limit},
        )
        return RagResult(
            answer=final.get("answer", "").strip(),
            sources=final.get("docs", []),
            steps=final.get("steps", []),
        )
