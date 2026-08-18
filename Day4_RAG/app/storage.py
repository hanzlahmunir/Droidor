"""The vector store boundary. Everything Chroma-specific lives here.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

Chroma will, if asked, pick an embedding model, embed your text, embed your
query, and decide what matches. None of that happens here. `embedding_function`
is left unset, so Chroma receives vectors we computed ourselves and returns
distances we convert and threshold ourselves.

Two reasons. The first is the task's: the retrieval loop is the part worth
learning, and handing it to the store hides it. The second is practical --
with the store reduced to `add` and `query`, replacing it touches this file
and nothing else. The retriever never imports chromadb.

ON DISTANCE VS SIMILARITY. Chroma returns a DISTANCE, and which distance
depends on the collection's configured space. This module pins the space to
cosine and converts to similarity in one place, because the two are inverted
with respect to each other and mixing them up produces a system that
confidently retrieves the WORST match for every question -- a bug that looks
like bad embeddings rather than a sign error.
"""

from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings

from app.config import Config

# Silence Chroma's telemetry logger.
#
# Telemetry is already disabled twice -- Settings(anonymized_telemetry=False)
# below, and ANONYMIZED_TELEMETRY=False in the Dockerfile -- but chromadb
# 0.5.23 still constructs its telemetry client and its FAILURE HANDLER is
# itself broken ("capture() takes 1 positional argument but 3 were given").
# The result is an error line per operation: three on `stats`, hundreds during
# ingest, all of them noise about an event that was never going to be sent.
#
# Suppressed at the logger rather than by patching the library, because the
# only thing wrong here is the logging. Scoped to this one module's namespace
# so nothing else is hidden.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

# Recorded on the collection so a later run can tell whether the vectors in it
# were produced by the model currently configured.
_META_EMBEDDING_MODEL = "embedding_model"
_META_CHUNK_SIZE = "chunk_size"
_META_CHUNK_OVERLAP = "chunk_overlap"

# Chroma supports several distance functions. Cosine is the right one for
# sentence-transformer embeddings, and pinning it explicitly matters: the
# default is L2, under which `1 - distance` is NOT a similarity and the floor
# in config.py would be meaningless.
_DISTANCE_SPACE = "cosine"

# HOW HARD THE APPROXIMATE SEARCH TRIES. This is not a performance knob here;
# it is a correctness one.
#
# Chroma indexes vectors with HNSW, a navigable graph. A query walks the graph
# toward the target rather than comparing against every vector, which is what
# keeps it fast at millions of vectors. The cost is that the walk can stop in a
# local minimum -- every neighbour looks worse, so it terminates -- while a
# better match sits elsewhere in the graph, unvisited.
#
# MEASURED ON THIS CORPUS, at the default search_ef of 10:
#
#   "Why did the author find Playwright unsatisfying for frontend tests?"
#     brute-force exact cosine over all 2195 chunks : 0.447  (Vue article)
#     what HNSW returned                            : 0.394  (a different one)
#
#   and it ALTERNATED between the two across process starts -- same vectors,
#   same collection, same query. Within one process it was stable; the
#   traversal differs between loads.
#
# That is bad on its own (an eval that is not reproducible is not a
# measurement), and worse here because the true score 0.447 sits just above
# the 0.425 floor: when the walk missed, the question flipped from answered to
# refused. A 0.022 margin was being decided by graph-traversal luck.
#
# search_ef is the size of the candidate list the walk keeps in play. Larger
# means more of the graph explored and higher recall, at the cost of a slower
# query. 200 over 2195 chunks costs single-digit milliseconds -- irrelevant at
# this scale, and cheap insurance against a silently wrong neighbour.
#
# NOTE it must be set at CREATION: Chroma refuses to modify index parameters on
# an existing collection, so changing it requires `ingest --reset`.
_SEARCH_EF = 200

# How thoroughly the graph is BUILT (vs searched). A denser graph at build time
# gives every later query a better chance of reaching the true neighbours.
# Default is 100; ingestion is a one-off cost measured in seconds here.
_CONSTRUCTION_EF = 400


class EmbeddingModelMismatch(RuntimeError):
    """The collection was built with a different embedding model.

    This is worth a hard failure rather than a warning. Vectors from two
    different models are not comparable -- querying MiniLM vectors with a
    vector from another model returns neighbours that are numerically valid
    and semantically meaningless. Nothing errors, the scores look plausible,
    and the answers are quietly wrong. Refusing to open the collection is the
    only way this surfaces at all.
    """


def _client(config: Config) -> chromadb.ClientAPI:
    """A persistent client rooted at the configured directory."""
    return chromadb.PersistentClient(
        path=config.chroma_dir,
        # Chroma phones home with usage telemetry by default. Off: this
        # processes other people's article text, and a tool that makes silent
        # outbound calls is not one whose network behaviour can be reasoned
        # about -- the same standard Day 3 applied to the crawler.
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )


def open_collection(config: Config) -> chromadb.Collection:
    """Open the collection for reading, creating it empty if absent.

    Verifies that the stored vectors came from the configured embedding model,
    and refuses to proceed if not. See EmbeddingModelMismatch.
    """
    collection = _client(config).get_or_create_collection(
        name=config.collection_name,
        metadata={
            "hnsw:space": _DISTANCE_SPACE,
            "hnsw:search_ef": _SEARCH_EF,
            "hnsw:construction_ef": _CONSTRUCTION_EF,
            _META_EMBEDDING_MODEL: config.embedding_model,
            _META_CHUNK_SIZE: config.chunk_size,
            _META_CHUNK_OVERLAP: config.chunk_overlap,
        },
    )

    # get_or_create returns the EXISTING collection when there is one, and its
    # metadata is whatever the original ingest recorded -- the dict above is
    # only applied on creation. So this compares against what is really
    # stored, not against what we just asked for.
    stored_model = (collection.metadata or {}).get(_META_EMBEDDING_MODEL)
    if stored_model and stored_model != config.embedding_model:
        raise EmbeddingModelMismatch(
            f"The collection '{config.collection_name}' was built with "
            f"embedding model '{stored_model}', but EMBEDDING_MODEL is now "
            f"'{config.embedding_model}'. Vectors from different models are "
            f"not comparable -- querying across them returns meaningless "
            f"neighbours without any error. Rebuild with: ingest --reset"
        )

    return collection


def reset_collection(config: Config) -> chromadb.Collection:
    """Delete the collection and recreate it empty.

    Used by `ingest --reset`. Needed whenever something that changes the
    MEANING of the stored vectors changes -- a different embedding model, a
    different chunk size -- because in both cases the existing rows are not
    wrong so much as incomparable, and incremental re-ingest would leave a
    collection containing both kinds.
    """
    client = _client(config)
    try:
        client.delete_collection(name=config.collection_name)
    except Exception:
        # Chroma raises if it does not exist. `--reset` on a clean checkout is
        # a normal thing to do, not an error.
        pass

    return client.create_collection(
        name=config.collection_name,
        metadata={
            "hnsw:space": _DISTANCE_SPACE,
            "hnsw:search_ef": _SEARCH_EF,
            "hnsw:construction_ef": _CONSTRUCTION_EF,
            _META_EMBEDDING_MODEL: config.embedding_model,
            _META_CHUNK_SIZE: config.chunk_size,
            _META_CHUNK_OVERLAP: config.chunk_overlap,
        },
    )


def distance_to_similarity(distance: float) -> float:
    """Convert Chroma's cosine distance into cosine similarity.

    Chroma's cosine space defines distance = 1 - cosine_similarity, so the
    inverse is simply 1 - distance. Similarity is the useful direction: it
    runs from -1 (opposite) through 0 (unrelated) to 1 (identical), which is
    what the configured floor is expressed in and what a reader can interpret.

    This exists as a named function, in this module, so the conversion happens
    exactly once. A second copy of `1 - d` somewhere else is how a sign error
    gets introduced on one path and not the other.
    """
    return 1.0 - distance
