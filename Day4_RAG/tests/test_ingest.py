"""Tests for the ingest pipeline.

Run against a REAL Chroma collection in a temporary directory, but with the
FakeEmbedder -- so the storage round-trip is genuinely exercised (ids,
metadata, upsert semantics) while no model is loaded and nothing is
downloaded. Chroma is the component whose behaviour we are relying on here;
mocking it would test the mock.
"""

import os

import pytest

from app.chunker import Chunk
from app.config import Config
from app.corpus import Article
from app.embedder import FakeEmbedder
from app.ingest import chunk_id, ingest
from app.storage import open_collection


@pytest.fixture
def config(tmp_path, monkeypatch) -> Config:
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("COLLECTION_NAME", "test_articles")
    monkeypatch.setenv("CHUNK_SIZE", "400")
    monkeypatch.setenv("CHUNK_OVERLAP", "50")
    monkeypatch.setenv("MIN_CHUNK_CHARS", "30")
    return Config()


def article(doc_id: int, *, title: str | None = None, text: str | None = None) -> Article:
    body = text or (
        f"## Section {doc_id}\n\n"
        + " ".join(f"word{i}" for i in range(120))
        + f"\n\n## Other {doc_id}\n\n"
        + " ".join(f"term{i}" for i in range(120))
    )
    return Article(
        id=doc_id,
        title=title or f"Article {doc_id}",
        url=f"https://example.com/{doc_id}",
        text=body,
        source="example.com",
    )


def test_ingest_stores_chunks_and_reports_counts(config):
    report = ingest(config, FakeEmbedder(), articles=[article(1), article(2)])

    assert report.articles_seen == 2
    assert report.articles_chunked == 2
    assert report.chunks_created > 0
    assert report.chunks_stored == report.chunks_created
    assert open_collection(config).count() == report.chunks_created


def test_re_ingesting_the_same_corpus_does_not_duplicate(config):
    # THE IDEMPOTENCE REQUIREMENT. Content-addressed ids mean the second run
    # overwrites the same rows. Without this, running ingest twice silently
    # doubles the corpus and every question retrieves the same chunk twice.
    articles = [article(1), article(2)]

    first = ingest(config, FakeEmbedder(), articles=articles)
    second = ingest(config, FakeEmbedder(), articles=articles)

    assert second.chunks_stored == first.chunks_stored
    assert open_collection(config).count() == first.chunks_created


def test_identical_text_in_two_articles_stays_two_chunks(config):
    # Two articles can legitimately share a paragraph -- a quoted licence, a
    # common snippet. Hashing on text alone would collapse them into one row
    # and the second article's citation would vanish.
    shared = "## Shared\n\n" + " ".join(f"word{i}" for i in range(120))
    both = [article(1, text=shared), article(2, text=shared)]

    ingest(config, FakeEmbedder(), articles=both)

    stored = open_collection(config).get(include=["metadatas"])
    doc_ids = {m["document_id"] for m in stored["metadatas"]}
    assert doc_ids == {1, 2}


def test_chunk_ids_are_stable_across_runs(config):
    chunk = Chunk(
        text="Some body text",
        heading="A Heading",
        ordinal=0,
        document_id=7,
        document_title="T",
        document_url="https://example.com/7",
        document_source="example.com",
    )
    assert chunk_id(chunk) == chunk_id(chunk)

    # ...and differ when the document differs, even for identical text.
    other = Chunk(**{**chunk.__dict__, "document_id": 8})
    assert chunk_id(chunk) != chunk_id(other)


def test_metadata_carries_everything_a_citation_needs(config):
    ingest(config, FakeEmbedder(), articles=[article(1, title="The Real Title")])

    stored = open_collection(config).get(include=["metadatas"])
    meta = stored["metadatas"][0]

    assert meta["document_title"] == "The Real Title"
    assert meta["document_url"] == "https://example.com/1"
    assert meta["document_source"] == "example.com"
    assert meta["document_id"] == 1
    # Chroma rejects None outright, so a chunk with no heading must store "".
    assert isinstance(meta["heading"], str)


def test_stored_document_text_excludes_the_heading_prefix(config):
    # The heading prefix is a retrieval aid, not part of the article. Quoting
    # it back to a reader as the author's words would be a small fabrication.
    ingest(config, FakeEmbedder(), articles=[article(1)])

    stored = open_collection(config).get(include=["documents", "metadatas"])
    for text, meta in zip(stored["documents"], stored["metadatas"]):
        heading = meta["heading"]
        if heading:
            assert not text.startswith(heading)


def test_articles_producing_no_chunks_are_reported(config):
    # An article too short to chunk contributes nothing to retrieval, and is
    # invisible to every question. That needs saying, not swallowing.
    stub = Article(
        id=9,
        title="A Stub",
        url="https://example.com/9",
        text="Too short.",
        source="example.com",
    )
    report = ingest(config, FakeEmbedder(), articles=[article(1), stub])

    assert report.articles_without_chunks == ["A Stub"]
    assert report.articles_chunked == 1


def test_empty_corpus_produces_an_empty_report_not_a_crash(config):
    report = ingest(config, FakeEmbedder(), articles=[])
    assert report.chunks_created == 0
    assert report.chunks_stored == 0


def test_changing_chunk_size_without_reset_is_refused(config, monkeypatch):
    # THE ORPHAN TRAP. Changing chunk size changes every content hash, so an
    # upsert leaves the old chunks in place with nothing to remove them. The
    # collection then holds two incompatible chunkings and a question can
    # retrieve both, citing one article twice with different text. Nothing
    # errors in that state, which is why it needs a guard.
    ingest(config, FakeEmbedder(), articles=[article(1)])

    monkeypatch.setenv("CHUNK_SIZE", "900")
    changed = Config()

    with pytest.raises(RuntimeError) as exc:
        ingest(changed, FakeEmbedder(), articles=[article(1)])
    assert "--reset" in str(exc.value)


def test_reset_rebuilds_from_scratch(config, monkeypatch):
    # --reset is the documented way out of the guard above. After it, the
    # collection must contain ONLY the new chunking -- no orphans from the
    # previous settings, and no rows from the article that was dropped.
    ingest(config, FakeEmbedder(), articles=[article(1), article(2)])

    monkeypatch.setenv("CHUNK_SIZE", "900")
    changed = Config()

    report = ingest(changed, FakeEmbedder(), articles=[article(1)], reset=True)

    assert report.was_reset is True
    collection = open_collection(changed)
    assert collection.count() == report.chunks_created

    # Article 2 was in the previous ingest and not in this one, so nothing
    # belonging to it may survive.
    stored = collection.get(include=["metadatas"])
    assert {m["document_id"] for m in stored["metadatas"]} == {1}


def test_fake_embedder_reports_no_truncation(config):
    # There is no model, so nothing is being truncated. Reporting 0 is correct
    # here rather than a silently skipped check.
    report = ingest(config, FakeEmbedder(), articles=[article(1)])
    assert report.chunks_truncated == 0
