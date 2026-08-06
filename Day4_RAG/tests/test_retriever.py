"""Tests for retrieval and the similarity floor.

Uses the FakeEmbedder against a real Chroma collection: the storage round-trip
and the ordering are genuinely exercised, but no model is loaded. The fake's
vectors are not semantically meaningful, so nothing here asserts that a
question finds the RIGHT article -- that is a property of the real embeddings
and is measured by `eval`. What is tested here is the machinery: ordering,
the threshold, the accept/reject split, and the context budget.
"""

import pytest

from app.config import Config
from app.corpus import Article
from app.embedder import FakeEmbedder
from app.ingest import ingest
from app.retriever import RetrievedChunk, build_context, retrieve
from app.storage import distance_to_similarity, open_collection


@pytest.fixture
def config(tmp_path, monkeypatch) -> Config:
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("COLLECTION_NAME", "test_retrieval")
    monkeypatch.setenv("CHUNK_SIZE", "400")
    monkeypatch.setenv("CHUNK_OVERLAP", "50")
    monkeypatch.setenv("MIN_CHUNK_CHARS", "30")
    return Config()


@pytest.fixture
def populated(config) -> Config:
    articles = [
        Article(
            id=i,
            title=f"Article {i}",
            url=f"https://example.com/{i}",
            text=f"## Topic {i}\n\n" + " ".join(f"word{i}_{j}" for j in range(100)),
            source="example.com",
        )
        for i in (1, 2, 3)
    ]
    ingest(config, FakeEmbedder(), articles=articles)
    return config


def test_distance_to_similarity_inverts_correctly():
    # A sign error here would retrieve the WORST match for every question
    # while looking entirely healthy, so it is worth pinning explicitly.
    assert distance_to_similarity(0.0) == pytest.approx(1.0)
    assert distance_to_similarity(1.0) == pytest.approx(0.0)
    assert distance_to_similarity(0.25) == pytest.approx(0.75)


def test_retrieve_returns_results_ordered_best_first(populated):
    result = retrieve("word1_5", populated, FakeEmbedder(), floor=-1.0)
    scores = [c.similarity for c in result.accepted]
    assert scores == sorted(scores, reverse=True)


def test_floor_splits_accepted_from_rejected(populated):
    # Everything above the floor is accepted, everything below rejected, and
    # nothing is lost between the two.
    loose = retrieve("word1_5", populated, FakeEmbedder(), floor=-1.0)
    total = len(loose.accepted) + len(loose.rejected)

    strict = retrieve("word1_5", populated, FakeEmbedder(), floor=0.99)
    assert len(strict.accepted) + len(strict.rejected) == total
    assert all(c.similarity >= 0.99 for c in strict.accepted)
    assert all(c.similarity < 0.99 for c in strict.rejected)


def test_impossible_floor_means_no_evidence(populated):
    # A floor of 1.0 accepts only an exact vector match, so this is the
    # refusal path: has_evidence must be False and the reason must name the
    # score that fell short.
    result = retrieve("anything", populated, FakeEmbedder(), floor=1.0)
    assert not result.has_evidence
    assert result.accepted == []
    assert "below the required" in result.explain_refusal()


def test_rejected_chunks_are_kept_for_explanation(populated):
    # A refusal with no near-misses is unexplainable. The UI shows these and
    # `eval` sweeps the floor against them.
    result = retrieve("anything", populated, FakeEmbedder(), floor=1.0)
    assert result.rejected
    assert result.best_similarity is not None


def test_top_k_limits_the_number_returned(populated):
    result = retrieve("word1_5", populated, FakeEmbedder(), top_k=2, floor=-1.0)
    assert len(result.accepted) + len(result.rejected) == 2


def test_empty_collection_yields_no_evidence(config):
    result = retrieve("anything", config, FakeEmbedder())
    assert not result.has_evidence
    assert result.best_similarity is None
    # The message must distinguish "nothing ingested" from "no good match" --
    # they need different fixes.
    assert "ingested" in result.explain_refusal()


def test_blank_question_is_not_sent_to_the_store(populated):
    assert not retrieve("   ", populated, FakeEmbedder()).has_evidence


def test_metadata_survives_the_round_trip(populated):
    result = retrieve("word1_5", populated, FakeEmbedder(), floor=-1.0)
    chunk = result.accepted[0]
    assert chunk.document_title.startswith("Article")
    assert chunk.document_url.startswith("https://example.com/")
    assert "(" in chunk.citation() and chunk.document_url in chunk.citation()


# --------------------------------------------------------------------------
# Context building: what the model is actually shown.
# --------------------------------------------------------------------------


def make_chunk(index: int, text: str, similarity: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        similarity=similarity,
        document_id=index,
        document_title=f"Article {index}",
        document_url=f"https://example.com/{index}",
        document_source="example.com",
        heading=f"Heading {index}",
    )


def test_context_numbers_sources_from_one(config):
    chunks = [make_chunk(1, "First body"), make_chunk(2, "Second body")]
    context, used = build_context(chunks, config)
    assert "[1]" in context and "[2]" in context
    assert len(used) == 2


def test_context_trimming_keeps_text_and_citations_in_agreement(config, monkeypatch):
    # THE INVARIANT THAT MATTERS. If a chunk is trimmed for length but still
    # appears in the citation list, the answer cites a source the model never
    # saw. build_context returns both so they cannot drift.
    monkeypatch.setenv("MAX_CONTEXT_CHARS", "200")
    tight = Config()

    chunks = [make_chunk(i, "x" * 150, similarity=1.0 - i / 10) for i in range(1, 6)]
    context, used = build_context(chunks, tight)

    assert len(used) < len(chunks)
    for index, chunk in enumerate(used, start=1):
        assert f"[{index}] {chunk.document_title}" in context


def test_context_always_includes_at_least_one_chunk(config, monkeypatch):
    # Even a single chunk over budget must be sent: returning nothing would
    # turn a retrievable answer into a spurious refusal.
    monkeypatch.setenv("MAX_CONTEXT_CHARS", "10")
    tiny = Config()

    context, used = build_context([make_chunk(1, "y" * 500)], tiny)
    assert len(used) == 1
    assert context


def test_context_includes_the_heading_as_shown_context(config):
    context, _ = build_context([make_chunk(1, "Body")], config)
    assert "Heading 1" in context
