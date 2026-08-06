"""Streamlit interface.

WHAT THIS SHOWS THAT THE CLI CANNOT. The interesting part of a RAG system is
not the answer -- it is the evidence, and the scores that decided whether the
evidence was good enough. So every query renders the retrieved chunks with
their similarity, the floor drawn as a line through them, and the near-misses
that were rejected.

That matters most on a REFUSAL. "I don't know" with nothing else is
indistinguishable from a broken index; "I don't know, the closest chunk scored
0.236 against a floor of 0.40, and here is what it was" is a diagnosis. Day 3
made the same argument for reporting every URL's status rather than only the
successes.

The sliders write to the same config values the CLI reads, so moving one here
demonstrates the tuning the task asks for -- chunk size and top-k as config,
not constants.
"""

from __future__ import annotations

import streamlit as st

from app.answerer import I_DONT_KNOW, AnswerError, generate_answer
from app.config import Config, ConfigError
from app.embedder import SentenceTransformerEmbedder
from app.retriever import retrieve
from app.storage import EmbeddingModelMismatch, open_collection

st.set_page_config(page_title="Ask the corpus", page_icon="?", layout="wide")


@st.cache_resource
def get_embedder(model_name: str) -> SentenceTransformerEmbedder:
    """Load the model once per session, not once per question.

    Keyed on the model name so changing EMBEDDING_MODEL invalidates the cache
    rather than silently serving vectors from the previous model.
    """
    config = Config()
    return SentenceTransformerEmbedder(config)


def render_chunk(index: int, chunk, accepted: bool) -> None:
    mark = "PASS" if accepted else "below floor"
    heading = f" - {chunk.heading}" if chunk.heading else ""
    with st.expander(
        f"[{index}] {chunk.similarity:.3f} {mark} - {chunk.document_title}{heading}",
        expanded=False,
    ):
        st.caption(chunk.document_url)
        st.text(chunk.text[:1200] + ("..." if len(chunk.text) > 1200 else ""))


def main() -> None:
    st.title("Ask the corpus")
    st.caption(
        "Retrieval-augmented question answering over the articles crawled on "
        "Day 3. Every answer cites its sources; questions the corpus cannot "
        "answer get \"I don't know\" rather than a guess."
    )

    try:
        config = Config()
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        return

    # ---------- sidebar: the tunables ----------
    with st.sidebar:
        st.header("Retrieval settings")
        st.caption(
            "These are config values, not constants. Changing them here "
            "affects this session only -- set them in .env to persist."
        )

        top_k = st.slider(
            "top_k - chunks retrieved",
            min_value=1,
            max_value=15,
            value=config.top_k,
            help="How many chunks the vector search returns.",
        )

        floor = st.slider(
            "similarity_floor - the refusal gate",
            min_value=0.0,
            max_value=0.9,
            value=config.similarity_floor,
            step=0.025,
            help=(
                "If the best chunk scores below this, the answer is "
                "\"I don't know\" and NO LLM call is made. Measured default: "
                "0.40 gives 100% recall and refuses 7 of 8 unanswerable "
                "questions. See data/reports/EVAL.md."
            ),
        )

        st.divider()
        st.caption(
            f"**chunk_size** {config.chunk_size} - "
            f"**overlap** {config.chunk_overlap}\n\n"
            "Changing these requires re-ingesting (`ingest --reset`), so they "
            "are not live sliders."
        )

        try:
            collection = open_collection(config)
            count = collection.count()
        except EmbeddingModelMismatch as exc:
            st.error(str(exc))
            return
        except Exception as exc:
            st.error(f"Could not open the vector store: {exc}")
            return

        st.metric("Chunks indexed", count)
        if count == 0:
            st.warning("Nothing ingested yet. Run `ingest` first.")

        if not config.groq_api_key:
            st.warning(
                "GROQ_API_KEY is not set. Retrieval works and sources are "
                "shown, but no answer can be generated."
            )

    if count == 0:
        st.info(
            "The vector store is empty. Run:\n\n"
            "```\ndocker compose run --rm rag ingest\n```"
        )
        return

    question = st.text_input(
        "Question",
        placeholder="What did running ANALYZE do to the slow SQLite query?",
    )

    if not question:
        return

    embedder = get_embedder(config.embedding_model)

    with st.spinner("Retrieving..."):
        result = retrieve(
            question, config, embedder, collection=collection, top_k=top_k, floor=floor
        )

    answer_column, evidence_column = st.columns([3, 2])

    with evidence_column:
        st.subheader("Evidence")
        st.caption(f"Floor: {floor:.3f}")
        if result.accepted:
            st.markdown(f"**{len(result.accepted)} chunk(s) above the floor**")
            for index, chunk in enumerate(result.accepted, start=1):
                render_chunk(index, chunk, accepted=True)
        if result.rejected:
            st.markdown(f"**{len(result.rejected)} rejected**")
            for index, chunk in enumerate(result.rejected, start=len(result.accepted) + 1):
                render_chunk(index, chunk, accepted=False)

    with answer_column:
        st.subheader("Answer")

        # THE REFUSAL GATE, before any LLM call.
        if not result.has_evidence:
            st.warning(I_DONT_KNOW)
            st.caption(result.explain_refusal())
            st.caption(
                "No tokens were spent: the refusal came from the similarity "
                "floor, before the model was called."
            )
            return

        try:
            with st.spinner("Generating..."):
                answer = generate_answer(question, result.accepted, config)
        except AnswerError as exc:
            st.error(str(exc))
            st.caption(
                "Retrieval succeeded -- the sources found are listed on the "
                "right."
            )
            return

        if answer.refused:
            st.warning(answer.text)
            st.caption(answer.reason)
            st.caption(
                "The chunks cleared the similarity floor, but the model "
                "judged that they do not contain the answer. This is the "
                "second refusal layer."
            )
            return

        st.markdown(answer.text)

        if answer.cited_sources:
            st.markdown("**Sources**")
            for index, source in enumerate(answer.cited_sources, start=1):
                st.markdown(f"{index}. {source}")
        else:
            st.caption(
                "No valid citations were returned -- treat this answer with "
                "suspicion."
            )


main()
