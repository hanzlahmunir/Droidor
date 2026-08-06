"""Corpus -> chunks -> vectors -> Chroma.

IDEMPOTENCE IS THE DESIGN CONSTRAINT. Running `ingest` twice must not double
the corpus. Chroma upserts by id, so the id has to be derived from the content
itself: the SHA-256 of the chunk's embeddable text plus its document id. Same
article, same chunker settings -> same ids -> the second run overwrites rather
than appends.

That also makes the failure mode of a CHANGED setting explicit. Alter
CHUNK_SIZE and every hash changes, so a plain re-ingest leaves the old chunks
sitting alongside the new ones -- a collection holding two incompatible
chunkings of the same corpus, quietly returning both. `ingest` detects that
(the stored settings are on the collection) and refuses, pointing at --reset.

WHAT IS REPORTED AND WHY. Day 3's lesson was that a pipeline which prints
"done" hides everything worth knowing. This reports what was skipped, what was
truncated, and how the chunks are distributed -- because "414 chunks stored"
and "414 chunks stored, 11 of which have unsearchable tails" are different
facts, and only the second one is actionable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.chunker import Chunk, chunk_markdown
from app.config import Config
from app.corpus import Article, load_articles
from app.embedder import Embedder
from app.storage import open_collection, reset_collection


@dataclass
class IngestReport:
    """What actually happened, in numbers that can be checked."""

    articles_seen: int = 0
    articles_chunked: int = 0
    articles_without_chunks: list[str] = field(default_factory=list)
    chunks_created: int = 0
    chunks_stored: int = 0
    chunks_truncated: int = 0
    truncated_examples: list[str] = field(default_factory=list)
    was_reset: bool = False
    settings: dict[str, object] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"Articles read from the API : {self.articles_seen}",
            f"Articles that produced chunks: {self.articles_chunked}",
            f"Chunks created             : {self.chunks_created}",
            f"Chunks stored              : {self.chunks_stored}",
        ]

        if self.articles_without_chunks:
            lines.append(
                f"Articles with NO chunks    : {len(self.articles_without_chunks)}"
            )
            for title in self.articles_without_chunks[:5]:
                lines.append(f"    - {title[:70]}")

        if self.chunks_truncated:
            # Stated plainly rather than buried: these chunks have tails that
            # contribute nothing to their vectors and cannot be retrieved.
            pct = 100 * self.chunks_truncated / max(self.chunks_created, 1)
            lines.append(
                f"Chunks over the model's token window: {self.chunks_truncated} "
                f"({pct:.1f}%) -- their tails are not searchable."
            )
            for example in self.truncated_examples[:3]:
                lines.append(f"    - {example}")

        return "\n".join(lines)


def chunk_id(chunk: Chunk) -> str:
    """A stable id derived from the chunk's content.

    Content-addressed so that re-ingesting an unchanged corpus overwrites the
    same rows instead of appending duplicates. The document id is included
    because two articles can legitimately share an identical paragraph (a
    quoted licence, a common code snippet), and collapsing those into one row
    would make the second article's citation disappear.
    """
    digest = hashlib.sha256()
    digest.update(str(chunk.document_id).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(chunk.embeddable_text().encode("utf-8"))
    return digest.hexdigest()


def build_chunks(articles: list[Article], config: Config) -> tuple[list[Chunk], list[str]]:
    """Chunk every article. Returns the chunks and the titles that produced none."""
    chunks: list[Chunk] = []
    empty: list[str] = []

    for article in articles:
        produced = chunk_markdown(
            article.text,
            document_id=article.id,
            document_title=article.title,
            document_url=article.url,
            document_source=article.source,
            config=config,
        )
        if produced:
            chunks.extend(produced)
        else:
            # Worth surfacing: an article in the corpus that contributes
            # nothing to retrieval is invisible to every question, and the
            # reason is usually that it is a stub below MIN_CHUNK_CHARS.
            empty.append(article.title)

    return chunks, empty


def ingest(
    config: Config,
    embedder: Embedder,
    *,
    reset: bool = False,
    articles: list[Article] | None = None,
) -> IngestReport:
    """Load, chunk, embed and store the corpus.

    `articles` is injectable so tests can ingest a fixed corpus without an API.
    """
    report = IngestReport(was_reset=reset, settings=config.describe())

    if articles is None:
        articles = load_articles(config)
    report.articles_seen = len(articles)

    chunks, empty = build_chunks(articles, config)
    report.chunks_created = len(chunks)
    report.articles_without_chunks = empty
    report.articles_chunked = len(articles) - len(empty)

    if not chunks:
        return report

    collection = reset_collection(config) if reset else open_collection(config)

    if not reset:
        _guard_against_mixed_chunkings(collection, config)

    texts = [c.embeddable_text() for c in chunks]

    # Count truncation BEFORE embedding, while the text is still whole. After
    # encode() the loss is invisible -- that is the entire problem with it.
    report.chunks_truncated, report.truncated_examples = _count_truncated(
        chunks, texts, embedder
    )

    vectors = embedder.embed_documents(texts)

    collection.upsert(
        ids=[chunk_id(c) for c in chunks],
        embeddings=vectors,
        # The chunk text WITHOUT the heading prefix. The prefix is a retrieval
        # aid, not part of the article: quoting it back to a reader as though
        # the author wrote it there would be a small fabrication.
        documents=[c.text for c in chunks],
        metadatas=[_metadata(c) for c in chunks],
    )

    report.chunks_stored = collection.count()
    return report


def _metadata(chunk: Chunk) -> dict[str, object]:
    """Everything a citation needs, carried on the chunk itself.

    Chroma metadata values must be scalars, so `heading` becomes "" rather
    than None -- None is rejected outright, and discovering that mid-ingest
    after embedding several hundred chunks is an expensive way to learn it.
    """
    return {
        "document_id": chunk.document_id,
        "document_title": chunk.document_title,
        "document_url": chunk.document_url,
        "document_source": chunk.document_source,
        "heading": chunk.heading or "",
        "ordinal": chunk.ordinal,
        "char_count": chunk.char_count,
    }


def _count_truncated(
    chunks: list[Chunk], texts: list[str], embedder: Embedder
) -> tuple[int, list[str]]:
    """How many chunks exceed the model's input window.

    Only possible with a real embedder that exposes a tokenizer; the fake one
    used in tests does not, and reporting zero there is correct rather than a
    silent failure -- there is no model, so nothing is being truncated.
    """
    count_tokens = getattr(embedder, "count_tokens", None)
    max_tokens = getattr(embedder, "max_tokens", None)
    if count_tokens is None or max_tokens is None:
        return 0, []

    truncated = 0
    examples: list[str] = []
    for chunk, text in zip(chunks, texts):
        tokens = count_tokens(text)
        if tokens > max_tokens:
            truncated += 1
            if len(examples) < 5:
                examples.append(
                    f"{tokens} tokens (limit {max_tokens}), "
                    f"{chunk.document_title[:45]}"
                )
    return truncated, examples


def _guard_against_mixed_chunkings(collection, config: Config) -> None:
    """Refuse to add differently-chunked content to an existing collection.

    Changing CHUNK_SIZE or CHUNK_OVERLAP changes every chunk boundary and
    therefore every content hash. Upserting on top of an existing collection
    would leave the OLD chunks in place as orphans -- nothing removes them,
    and they keep being returned by searches. The collection then holds two
    incompatible chunkings of the same articles, and a question can retrieve
    both, citing the same article twice with different text.

    Nothing errors in that state, which is exactly why it needs a guard.
    """
    stored = collection.metadata or {}
    stored_size = stored.get("chunk_size")
    stored_overlap = stored.get("chunk_overlap")

    if collection.count() == 0:
        return

    mismatches = []
    if stored_size is not None and int(stored_size) != config.chunk_size:
        mismatches.append(f"chunk_size {stored_size} -> {config.chunk_size}")
    if stored_overlap is not None and int(stored_overlap) != config.chunk_overlap:
        mismatches.append(f"chunk_overlap {stored_overlap} -> {config.chunk_overlap}")

    if mismatches:
        raise RuntimeError(
            "The existing collection was built with different chunking "
            f"settings ({'; '.join(mismatches)}). Re-ingesting on top of it "
            "would leave the old chunks in place as orphans, so the same "
            "article could be retrieved twice with different text. "
            "Rebuild instead: ingest --reset"
        )
