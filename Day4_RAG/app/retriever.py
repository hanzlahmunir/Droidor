"""The retrieval loop, written by hand.

This is the module the task is actually about: embed the question, find the
nearest chunks, decide whether they are good enough to answer from. No
framework does any of it.

THE REFUSAL GATE LIVES HERE, NOT IN THE PROMPT. If the best chunk scores below
the configured floor, `retrieve` returns nothing and `ask` refuses without
calling an LLM at all. That ordering matters for three reasons:

  1. It is deterministic. The same question always produces the same verdict,
     so the refusal can be unit-tested with a fake embedder and measured by
     `eval` -- neither of which is true of "the model decided to abstain".
  2. It costs nothing. A question the corpus cannot answer spends no tokens.
  3. It cannot be talked around. A prompt instruction is a request; a
     threshold is a rule.

The prompt ALSO instructs abstention, as a second layer -- chunks can clear
the floor on topic overlap while not containing the answer. But the layer that
can be measured is this one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.embedder import Embedder
from app.storage import distance_to_similarity, open_collection


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk the search returned, with the score that got it there."""

    text: str
    similarity: float
    document_id: int
    document_title: str
    document_url: str
    document_source: str
    heading: str

    def citation(self) -> str:
        return f"{self.document_title} ({self.document_url})"


@dataclass(frozen=True)
class RetrievalResult:
    """What the search found, and whether it was good enough to answer from.

    Carries the REJECTED chunks as well as the accepted ones. That is
    deliberate: when the system refuses, the useful question is "what did it
    nearly match, and by how much" -- and without the near-misses a refusal is
    unexplainable. The UI shows them, and `eval` uses them to sweep the floor.
    """

    query: str
    accepted: list[RetrievedChunk]
    rejected: list[RetrievedChunk]
    floor: float

    @property
    def has_evidence(self) -> bool:
        return bool(self.accepted)

    @property
    def best_similarity(self) -> float | None:
        """The top score seen, accepted or not."""
        both = self.accepted + self.rejected
        return max((c.similarity for c in both), default=None)

    def explain_refusal(self) -> str:
        """Why nothing was good enough. Shown to the user on a refusal."""
        best = self.best_similarity
        if best is None:
            return "The vector store returned no chunks at all -- is anything ingested?"
        # Both numbers at the same precision. The floor was printed at 2dp
        # while the score used 3, so a floor of 0.425 rendered as "the
        # required 0.42" -- a number that appears nowhere in the config and
        # does not match the README, which is exactly the kind of small
        # inconsistency that makes a reviewer distrust the rest of the output.
        return (
            f"The closest chunk scored {best:.3f}, below the required "
            f"{self.floor:.3f}. Nothing in the corpus is a close enough match."
        )


def retrieve(
    query: str,
    config: Config,
    embedder: Embedder,
    *,
    collection=None,
    top_k: int | None = None,
    floor: float | None = None,
) -> RetrievalResult:
    """Embed the question, search, and apply the similarity floor.

    `top_k` and `floor` override config so `eval` can sweep them without
    reconstructing a Config per trial -- which is the whole reason they are
    configuration in the first place.
    """
    collection = collection if collection is not None else open_collection(config)
    k = top_k if top_k is not None else config.top_k
    threshold = floor if floor is not None else config.similarity_floor

    if not query.strip():
        return RetrievalResult(query=query, accepted=[], rejected=[], floor=threshold)

    # An empty collection is not an error, but querying it returns nothing and
    # the resulting refusal would look identical to "no good match". Checking
    # here lets `ask` say "nothing is ingested" instead.
    if collection.count() == 0:
        return RetrievalResult(query=query, accepted=[], rejected=[], floor=threshold)

    query_vector = embedder.embed_query(query)

    response = collection.query(
        query_embeddings=[query_vector],
        # Never ask for more than exist: Chroma warns and clamps, and the warning
        # is noise on a small corpus.
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    accepted: list[RetrievedChunk] = []
    rejected: list[RetrievedChunk] = []

    # Chroma returns one list per query; we send exactly one.
    documents = (response.get("documents") or [[]])[0]
    metadatas = (response.get("metadatas") or [[]])[0]
    distances = (response.get("distances") or [[]])[0]

    for text, metadata, distance in zip(documents, metadatas, distances):
        chunk = RetrievedChunk(
            text=text,
            # Converted in exactly one place (app.storage), because a second
            # copy of `1 - d` is how a sign error gets introduced on one path
            # and not the other -- and a sign error here retrieves the WORST
            # match for every question while looking entirely healthy.
            similarity=distance_to_similarity(distance),
            document_id=int(metadata.get("document_id", -1)),
            document_title=str(metadata.get("document_title", "Unknown")),
            document_url=str(metadata.get("document_url", "")),
            document_source=str(metadata.get("document_source", "")),
            heading=str(metadata.get("heading", "")),
        )
        (accepted if chunk.similarity >= threshold else rejected).append(chunk)

    # Chroma returns nearest-first, but that is a property of its index rather
    # than a documented guarantee of this function. Sorting explicitly means
    # "best first" is true because we made it true -- and the context builder
    # below relies on it when it trims to the character budget.
    accepted.sort(key=lambda c: c.similarity, reverse=True)
    rejected.sort(key=lambda c: c.similarity, reverse=True)

    return RetrievalResult(
        query=query, accepted=accepted, rejected=rejected, floor=threshold
    )


def build_context(
    chunks: list[RetrievedChunk], config: Config
) -> tuple[str, list[RetrievedChunk]]:
    """Format accepted chunks as numbered sources, within the character budget.

    Returns the prompt text AND the chunks that actually made it in. Those two
    must agree: if a chunk is trimmed for length but still appears in the
    citation list, the answer cites a source the model never saw. Returning
    both is what keeps them from drifting.

    Chunks are added best-first, so trimming drops the weakest evidence rather
    than an arbitrary tail.
    """
    used: list[RetrievedChunk] = []
    parts: list[str] = []
    total = 0

    for index, chunk in enumerate(chunks, start=1):
        heading = f" -- {chunk.heading}" if chunk.heading else ""
        block = f"[{index}] {chunk.document_title}{heading}\n{chunk.text}"

        if total + len(block) > config.max_context_chars and used:
            break

        parts.append(block)
        used.append(chunk)
        total += len(block)

    return "\n\n".join(parts), used
