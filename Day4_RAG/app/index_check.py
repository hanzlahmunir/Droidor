"""Verify the approximate index against exact cosine similarity.

WHY THIS EXISTS. Chroma indexes vectors with HNSW, a navigable graph. A query
walks the graph toward the target instead of comparing against every vector --
which is what keeps vector search fast at millions of vectors, and which means
the result is APPROXIMATE. The walk can terminate in a local minimum while a
better match sits elsewhere in the graph, unvisited.

Nothing reports this. The query returns plausible neighbours with plausible
scores, and the only way to know they are not the true nearest is to compute
the true nearest and compare. That is what this module does.

IT FOUND A REAL PROBLEM. At Chroma's default search_ef of 10, on this corpus:

    "Why did the author find Playwright unsatisfying for frontend tests?"
      exact cosine over all 2195 chunks : 0.447  (the Vue article)
      what the index returned           : 0.394  (a different article)

and it alternated between the two across process starts -- same vectors, same
collection, same query. Because the true score (0.447) sits just above the
similarity floor (0.425), the question flipped between answered and refused
depending on which way the traversal went. An eval that is not reproducible is
not a measurement.

Brute force is O(n) over the whole collection, which is exactly what a vector
index exists to avoid -- so this is a diagnostic to run deliberately, not part
of the query path. At 2195 chunks it takes well under a second.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.embedder import Embedder
from app.storage import distance_to_similarity


@dataclass
class IndexCheckResult:
    """How far the index's answer was from the true answer, per question."""

    question: str
    exact_best: float
    index_best: float
    exact_title: str
    index_title: str

    @property
    def gap(self) -> float:
        """How much similarity the index left on the table. 0.0 is perfect."""
        return self.exact_best - self.index_best

    @property
    def wrong_article(self) -> bool:
        """The index returned a different article than the true nearest.

        Worse than a small score gap: the citation itself would be wrong.
        """
        return self.exact_title != self.index_title


def check_index(
    questions: list[str],
    config: Config,
    embedder: Embedder,
    *,
    collection=None,
    tolerance: float = 0.005,
) -> tuple[list[IndexCheckResult], list[IndexCheckResult]]:
    """Compare index results against exact cosine for every question.

    Returns (all_results, results_exceeding_tolerance).
    """
    import numpy as np

    from app.storage import open_collection

    collection = collection if collection is not None else open_collection(config)

    stored = collection.get(include=["embeddings", "metadatas"])
    matrix = np.array(stored["embeddings"])
    metadatas = stored["metadatas"]

    results: list[IndexCheckResult] = []

    for question in questions:
        vector = np.array(embedder.embed_query(question))

        # Exact: one dot product against every stored vector. Embeddings are
        # L2-normalised, so the dot product IS the cosine similarity.
        scores = matrix @ vector
        best_index = int(scores.argmax())

        response = collection.query(
            query_embeddings=[vector.tolist()],
            n_results=min(config.top_k, collection.count()),
            include=["metadatas", "distances"],
        )

        index_best = distance_to_similarity(response["distances"][0][0])
        index_title = str(response["metadatas"][0][0].get("document_title", "?"))

        results.append(
            IndexCheckResult(
                question=question,
                exact_best=float(scores[best_index]),
                index_best=index_best,
                exact_title=str(metadatas[best_index].get("document_title", "?")),
                index_title=index_title,
            )
        )

    return results, [r for r in results if r.gap > tolerance]


def format_check(
    results: list[IndexCheckResult], misses: list[IndexCheckResult]
) -> str:
    """A short report on index accuracy."""
    lines = [
        f"Checked {len(results)} questions against exact cosine similarity.",
        "",
    ]

    if not misses:
        lines.append("  The index returned the true nearest chunk every time.")
        return "\n".join(lines)

    worst = max(r.gap for r in misses)
    wrong_article = sum(1 for r in misses if r.wrong_article)

    lines.append(
        f"  {len(misses)}/{len(results)} questions got a sub-optimal top-1 "
        f"(worst gap {worst:.3f})."
    )
    lines.append(
        f"  {wrong_article} of those returned a DIFFERENT article than the "
        f"true nearest."
    )
    lines.append("")

    for result in sorted(misses, key=lambda r: -r.gap):
        lines.append(
            f"    gap {result.gap:.3f}  exact {result.exact_best:.3f} "
            f"vs index {result.index_best:.3f}  {result.question[:48]}"
        )
        if result.wrong_article:
            lines.append(f"        true : {result.exact_title[:56]}")
            lines.append(f"        index: {result.index_title[:56]}")

    return "\n".join(lines)
