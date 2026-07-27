"""RAG Testbed — Streamlit UI.

Add multiple config windows across the top, each an independent RAG pipeline
(LLM x effort x framework x store). Type one query at the bottom, hit Run All,
and every window runs the query **in parallel** — each showing its answer and,
prominently, how long it took, so setups can be compared on quality and speed.

Run:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from config import (
    EFFORT_DEFAULT,
    EFFORT_MAX,
    EFFORT_MIN,
    FRAMEWORKS,
    K_DEFAULT,
    K_MAX,
    K_MIN,
    REASONING_LEVELS,
    STORES,
    RagConfig,
)
from layout_store import load_layout, save_layout
from llms.registry import available_providers, models_for, provider_label
from rag_runner import run_all

st.set_page_config(page_title="RAG Testbed", page_icon="🧪", layout="wide")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def _default_window() -> dict:
    providers = available_providers()
    prov = providers[0] if providers else ""
    models = models_for(prov)
    return {
        "provider": prov,
        "model": models[0] if models else "",
        "effort": EFFORT_DEFAULT,
        "framework": FRAMEWORKS[0],
        "store": STORES[0],
        "k": K_DEFAULT,
        "rewrite_query": True,
        "grade_docs": True,
        "reasoning_effort": "medium",
    }


def _restore_windows() -> list[dict]:
    """Load saved layout on first render; fall back to a single default window."""
    saved = load_layout()
    if not saved:
        return [_default_window()]
    # Repair any saved window whose provider/model is no longer available.
    provs = available_providers()
    restored = []
    for w in saved:
        base = _default_window()
        base.update({k: w[k] for k in base if w.get(k) is not None})
        if provs and base["provider"] not in provs:
            base = _default_window()  # provider gone (key removed) -> reset
        restored.append(base)
    return restored or [_default_window()]


if "windows" not in st.session_state:
    st.session_state.windows = _restore_windows()
if "results" not in st.session_state:
    st.session_state.results = {}  # index -> RagResult


def add_window() -> None:
    st.session_state.windows.append(_default_window())
    save_layout(st.session_state.windows)


def remove_window(i: int) -> None:
    st.session_state.windows.pop(i)
    st.session_state.results = {}
    save_layout(st.session_state.windows)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🧪 RAG Testbed")
st.caption(
    "Compare RAG pipelines side-by-side. Each window is one configuration; "
    "one query runs through all of them in parallel."
)

providers = available_providers()
if not providers:
    st.error(
        "No LLM providers available. Add at least one API key to `.env` "
        "(e.g. `GROQ_API_KEY=...`) and restart. See `.env.example`."
    )

top = st.columns([1, 6])
with top[0]:
    st.button("➕ Add window", on_click=add_window, use_container_width=True, type="primary")
with top[1]:
    st.write(f"**{len(st.session_state.windows)}** configuration window(s)")


# --------------------------------------------------------------------------- #
# Config windows — grid, max WINDOWS_PER_ROW per row then wrap downward
# --------------------------------------------------------------------------- #
WINDOWS_PER_ROW = 4


def render_window(i: int, win: dict) -> None:
    """Render one config window (controls + result) into the current column."""
    with st.container(border=True):
        head = st.columns([5, 1])
        head[0].markdown(f"**Window {i + 1}**")
        head[1].button("🗑", key=f"rm_{i}", on_click=remove_window, args=(i,),
                       help="Remove this window")

        # Provider
        prov_opts = providers or [win["provider"]]
        prov_idx = prov_opts.index(win["provider"]) if win["provider"] in prov_opts else 0
        win["provider"] = st.selectbox(
            "LLM provider", prov_opts, index=prov_idx,
            format_func=provider_label, key=f"prov_{i}",
        )

        # Model (depends on provider)
        model_opts = models_for(win["provider"]) or [win["model"]]
        model_idx = model_opts.index(win["model"]) if win["model"] in model_opts else 0
        win["model"] = st.selectbox("Model", model_opts, index=model_idx, key=f"model_{i}")

        # Framework + store
        win["framework"] = st.selectbox(
            "Framework", FRAMEWORKS,
            index=FRAMEWORKS.index(win["framework"]), key=f"fw_{i}",
        )

        win["store"] = st.selectbox(
            "Data store", STORES,
            index=STORES.index(win["store"]), key=f"store_{i}",
        )

        is_langchain = win["framework"] == "langchain"

        # Effort = max reform rounds. Only LangGraph loops; disabled on LangChain.
        win["effort"] = st.number_input(
            "Max reform rounds", min_value=EFFORT_MIN, max_value=EFFORT_MAX,
            value=int(win["effort"]), step=1, key=f"effort_{i}",
            disabled=is_langchain,
            help=(
                "How many times the agent may reform the query and re-search "
                f"before answering (LangGraph only). Capped at {EFFORT_MAX}."
            ),
        )
        if is_langchain:
            st.caption("⚠️ LangChain is single-shot — reform rounds don't apply.")

        # ---- Advanced: independent retrieval / reasoning knobs ----
        with st.expander("⚙️ Advanced"):
            win["k"] = st.number_input(
                "Chunks retrieved (k)", min_value=K_MIN, max_value=K_MAX,
                value=int(win.get("k", K_DEFAULT)), step=1, key=f"k_{i}",
                help="How many product chunks to pull from the store per retrieval.",
            )
            win["rewrite_query"] = st.checkbox(
                "Query rewrite", value=bool(win.get("rewrite_query", True)),
                key=f"rw_{i}",
                help="LLM rewrites your question into a keyword search query first.",
            )
            win["grade_docs"] = st.checkbox(
                "Doc grading + retry", value=bool(win.get("grade_docs", True)),
                key=f"grade_{i}", disabled=is_langchain,
                help="Grade retrieved docs; if weak, reform & retry (LangGraph only).",
            )
            if is_langchain:
                st.caption("Doc grading applies to LangGraph only.")
            lvl = win.get("reasoning_effort", "medium")
            win["reasoning_effort"] = st.selectbox(
                "Reasoning effort", REASONING_LEVELS,
                index=REASONING_LEVELS.index(lvl) if lvl in REASONING_LEVELS else 1,
                key=f"reason_{i}",
                help="Native model reasoning level, where the model supports it.",
            )

        # ---- Result area (populated after Run All) ----
        res = st.session_state.results.get(i)
        if res is not None:
            st.divider()
            if res.error:
                st.error(res.error)
            else:
                st.metric("⏱ Time", f"{res.latency_s:.2f}s")
                st.markdown("**Answer**")
                st.write(res.answer or "_(empty)_")
                meta = []
                if res.tokens is not None:
                    meta.append(f"{res.tokens} tokens")
                if res.cost is not None:
                    meta.append(f"${res.cost:.4f}")
                if meta:
                    st.caption(" · ".join(meta))
                with st.expander(f"Sources ({len(res.sources)}) & trace"):
                    if res.steps:
                        st.caption("Pipeline: " + " → ".join(res.steps))
                    for d in res.sources:
                        st.markdown(f"- **{d.metadata.get('title', '(untitled)')}**")


windows = st.session_state.windows
for row_start in range(0, len(windows), WINDOWS_PER_ROW):
    row = windows[row_start : row_start + WINDOWS_PER_ROW]
    # Divide the row's width by how many windows are actually in THIS row (capped
    # at WINDOWS_PER_ROW), so a row of 2 gives two half-width cards with no empty
    # gap, while a full row of 4 gives quarter-width cards.
    cols = st.columns(len(row))
    for offset, win in enumerate(row):
        with cols[offset]:
            render_window(row_start + offset, win)


# --------------------------------------------------------------------------- #
# Query box (bottom) + Run All
# --------------------------------------------------------------------------- #
st.divider()
query = st.text_area("Query", placeholder="e.g. What's a good co-op board game for kids?", height=80)
run = st.button("▶ Run All", type="primary", disabled=not providers, use_container_width=True)

if run:
    if not query.strip():
        st.warning("Enter a query first.")
    else:
        configs = [
            RagConfig(
                llm_provider=w["provider"], llm_model=w["model"], effort=w["effort"],
                framework=w["framework"], store=w["store"],
                k=w.get("k", K_DEFAULT),
                rewrite_query=w.get("rewrite_query", True),
                grade_docs=w.get("grade_docs", True),
                reasoning_effort=w.get("reasoning_effort", "medium"),
            )
            for w in st.session_state.windows
        ]
        # Persist current window configs (captures any dropdown/slider changes).
        save_layout(st.session_state.windows)
        with st.spinner(f"Running {len(configs)} pipeline(s) in parallel..."):
            results = run_all(configs, query.strip())
        st.session_state.results = dict(enumerate(results))
        # Stash the full run so it can be exported (also auto-saved to runs/ by run_all).
        st.session_state.last_run = {"query": query.strip(), "configs": configs, "results": results}
        st.rerun()

# Download button for the most recent run (results auto-saved to runs/ too).
if st.session_state.get("last_run"):
    from run_store import markdown_for

    lr = st.session_state.last_run
    md = markdown_for("export", lr["query"], lr["configs"], lr["results"])
    st.download_button(
        "⬇ Download results (.md)", md,
        file_name="rag_run.md", mime="text/markdown",
    )
    st.caption("Every run is also auto-saved to the `runs/` folder (JSON + markdown).")
