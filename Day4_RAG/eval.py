"""Score the RAG system against eval_set.json. One command, five numbers.

    python eval.py                 # the five lines
    python eval.py --verbose       # plus a per-question table
    python eval.py --no-llm        # retrieval only, no API calls, no answers
    python eval.py --json-out r.json

WHAT THE FIVE NUMBERS MEAN, and why each is measured the way it is.

  Top-1 / Top-5 -- RETRIEVAL. Ranking is computed over ARTICLES, not chunks.
      The retriever returns top_k=12 chunks, and on this corpus the first
      five chunks are frequently five chunks of the SAME article. Ranking
      those directly would make "top-5" nearly free. So chunks are collapsed
      to their document_id, first occurrence wins, and the resulting article
      ranking is what gets scored. Top-5 therefore means five distinct
      articles, which is the question the metric is supposed to ask.

      Scored over the 16 questions that have expected articles. The 4
      unanswerable ones have none, so they are excluded rather than counted
      as failures -- a system that retrieves nothing for them is behaving
      correctly, and folding that into a retrieval score would reward
      retrieval for refusing.

      Ranking uses the chunks BEFORE the similarity floor is applied
      (accepted + rejected, re-sorted by score). The floor is a refusal
      policy, not a retrieval result; measuring them separately is what
      makes it possible to tell "the search missed it" apart from "the
      search found it and the floor threw it away". Those have opposite
      fixes and the same symptom.

  Answer correct -- every must_contain token appears in the generated answer.
      Substring, case-insensitive. A nested list is OR: [["beginning",
      "front"]] passes on either, which keeps the metric from punishing
      correct answers for word choice. Scored over the same 16.

  Refused correctly -- of the 4 unanswerable questions, how many produced
      "I don't know". Either refusal layer counts: the similarity floor
      (before any LLM call) or the model abstaining. The breakdown of which
      layer fired is in --verbose, because the floor is the deterministic one
      and drift between them is worth watching.

WHY --no-llm EXISTS. The 5-line report needs the LLM for two of its lines, and
Groq rate-limits when questions are fired back to back. --no-llm gives the
retrieval half in seconds with no key and no network, which is the half that
changes when chunking or top_k is tuned.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.answerer import AnswerError, generate_answer, looks_like_refusal  # noqa: E402
from app.config import Config  # noqa: E402
from app.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.retriever import RetrievedChunk, retrieve  # noqa: E402
from app.storage import open_collection  # noqa: E402

EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"

# Between LLM calls. Day 4 hit Groq 429s running the eval set back to back and
# lost a question to it, which silently cost a point on a metric that is
# supposed to measure the retriever.
LLM_PAUSE_SECONDS = 1.5


@dataclass
class Outcome:
    """What happened for one question."""

    id: int
    question: str
    type: str
    expected: list[int]
    must_contain: list
    ranked_articles: list[int] = field(default_factory=list)
    answer: str = ""
    refused: bool = False
    refused_before_llm: bool = False
    missing_tokens: list[str] = field(default_factory=list)
    best_similarity: float | None = None
    error: str = ""

    @property
    def scored_for_retrieval(self) -> bool:
        """Unanswerable questions have no correct article, so they sit out."""
        return bool(self.expected)

    @property
    def top_1(self) -> bool:
        return bool(self.ranked_articles) and self.ranked_articles[0] in self.expected

    @property
    def top_5(self) -> bool:
        return any(a in self.expected for a in self.ranked_articles[:5])

    @property
    def answer_correct(self) -> bool:
        return bool(self.answer) and not self.refused and not self.missing_tokens

    @property
    def refused_correctly(self) -> bool:
        return self.refused


def load_eval_set(path: Path = EVAL_SET) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"No eval set at {path}. Expected eval_set.json beside eval.py.")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    questions = data["questions"] if isinstance(data, dict) else data
    if not questions:
        raise SystemExit(f"{path} contains no questions.")
    return questions


def rank_articles(chunks: list[RetrievedChunk]) -> list[int]:
    """Collapse chunks to a ranked list of distinct article ids.

    First occurrence wins: an article's rank is the rank of its best chunk.
    Without this collapse, "top-5" would often mean "five chunks of one
    article" and the metric would flatter the system.
    """
    seen: dict[int, None] = {}
    for chunk in sorted(chunks, key=lambda c: c.similarity, reverse=True):
        seen.setdefault(chunk.document_id, None)
    return list(seen)


def normalise(text: str) -> str:
    """Fold the differences that are typography rather than meaning.

    Three real false negatives from the first baseline run, every one of them
    a correct answer scored wrong:

      "5-second write timeout"  vs  must_contain "5 second"
      "about 8 KB"              vs  must_contain "8KB"
      "line-buffered"           vs  must_contain "--line-buffered"

    The first two are the model writing a U+2011 non-breaking hyphen and a
    thin space -- it renders identically and means identically. Scoring them
    as failures would make the metric measure the model's typographic habits,
    which is exactly the noise a baseline needs to be free of.

    So: unicode dashes fold to ASCII, then whitespace and hyphens are removed
    entirely, on BOTH sides. "5 second", "5-second" and "5‑second" all
    become "5second". This is deliberately aggressive; must_contain tokens are
    short and specific enough that over-matching is not a realistic risk, and
    a metric that is wrong in the strict direction is still wrong.
    """
    folded = text.lower()
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        folded = folded.replace(dash, "-")
    folded = folded.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return re.sub(r"[\s\-]+", "", folded)


def missing(must_contain: list, text: str) -> list[str]:
    """Which required tokens are absent. A nested list is satisfied by any one.

    Normalised substring, not a semantic check, and that is on purpose: the
    point of a baseline is that tomorrow's number is comparable to today's,
    and an LLM judge would move under us for reasons unrelated to the change
    we are trying to measure.
    """
    haystack = normalise(text)
    absent: list[str] = []
    for requirement in must_contain:
        options = requirement if isinstance(requirement, list) else [requirement]
        if not any(normalise(str(o)) in haystack for o in options):
            absent.append(" | ".join(str(o) for o in options))
    return absent


def run_question(
    entry: dict,
    config: Config,
    embedder,
    collection,
    *,
    use_llm: bool,
) -> Outcome:
    outcome = Outcome(
        id=entry["id"],
        question=entry["question"],
        type=entry.get("type", "single"),
        expected=list(entry.get("expect_article_ids") or []),
        must_contain=list(entry.get("must_contain") or []),
    )

    result = retrieve(entry["question"], config, embedder, collection=collection)
    # Rank over everything the search returned, floor or no floor -- see the
    # module docstring on why retrieval and refusal are measured apart.
    outcome.ranked_articles = rank_articles(result.accepted + result.rejected)
    outcome.best_similarity = result.best_similarity

    # Layer 1: the similarity floor. Deterministic, and costs nothing.
    if not result.has_evidence:
        outcome.refused = True
        outcome.refused_before_llm = True
        return outcome

    if not use_llm:
        return outcome

    try:
        answer = generate_answer(entry["question"], result.accepted, config)
    except AnswerError as exc:
        outcome.error = str(exc)
        return outcome

    outcome.answer = answer.text
    # Layer 2: the model abstaining on chunks that cleared the floor without
    # containing the answer. `looks_like_refusal` is reused rather than
    # re-implemented so this agrees with what the CLI calls a refusal.
    outcome.refused = answer.refused or looks_like_refusal(answer.text)

    if not outcome.refused:
        outcome.missing_tokens = missing(outcome.must_contain, answer.text)

    return outcome


def report(outcomes: list[Outcome], *, use_llm: bool) -> str:
    retrieval = [o for o in outcomes if o.scored_for_retrieval]
    unanswerable = [o for o in outcomes if not o.scored_for_retrieval]

    total = len(outcomes)
    n = len(retrieval) or 1
    top1 = sum(o.top_1 for o in retrieval)
    top5 = sum(o.top_5 for o in retrieval)
    correct = sum(o.answer_correct for o in retrieval)
    refused = sum(o.refused_correctly for o in unanswerable)

    def pct(hits: int) -> str:
        return f"({round(100 * hits / n)}%)"

    lines = [
        f"Questions:         {total}",
        f"Top-1 correct:     {top1}/{len(retrieval)}  {pct(top1)}",
        f"Top-5 correct:     {top5}/{len(retrieval)}  {pct(top5)}",
        (
            f"Answer correct:    {correct}/{len(retrieval)}  {pct(correct)}"
            if use_llm
            else "Answer correct:    -- (--no-llm)"
        ),
        f"Refused correctly:  {refused}/{len(unanswerable)}",
    ]
    return "\n".join(lines)


def verbose_table(outcomes: list[Outcome]) -> str:
    rows = [
        "",
        "Per question:",
        f"  {'id':>2}  {'type':<12} {'top1':<5} {'top5':<5} {'ans':<5} "
        f"{'best':<6} detail",
    ]
    for o in outcomes:
        if o.scored_for_retrieval:
            t1 = "yes" if o.top_1 else "NO"
            t5 = "yes" if o.top_5 else "NO"
            ans = "yes" if o.answer_correct else "NO"
        else:
            t1 = t5 = "-"
            ans = "ok" if o.refused else "ANSWERED"

        detail = ""
        if o.error:
            detail = f"ERROR: {o.error[:60]}"
        elif o.missing_tokens:
            detail = "missing: " + ", ".join(o.missing_tokens)
        elif o.refused:
            layer = "floor" if o.refused_before_llm else "prompt"
            detail = f"refused ({layer})"
        elif o.scored_for_retrieval and not o.top_1 and o.ranked_articles:
            detail = (
                f"wanted {o.expected}, got {o.ranked_articles[:5]}"
            )

        best = f"{o.best_similarity:.3f}" if o.best_similarity is not None else "  -  "
        rows.append(
            f"  {o.id:>2}  {o.type:<12} {t1:<5} {t5:<5} {ans:<5} {best:<6} {detail}"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the RAG system. Prints 5 lines.")
    parser.add_argument("--verbose", action="store_true", help="Per-question table.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Retrieval only: no API calls, no answers, no key needed.",
    )
    parser.add_argument("--json-out", default=None, help="Write full results as JSON.")
    args = parser.parse_args()

    config = Config()
    collection = open_collection(config)
    if collection.count() == 0:
        raise SystemExit(
            "Nothing is ingested, so every question would score zero. Run:\n"
            "  docker compose run --rm rag ingest --reset"
        )

    embedder = SentenceTransformerEmbedder(config)
    questions = load_eval_set()
    use_llm = not args.no_llm

    outcomes: list[Outcome] = []
    for index, entry in enumerate(questions):
        outcomes.append(
            run_question(entry, config, embedder, collection, use_llm=use_llm)
        )
        # Only pause when a call was actually made and another is coming.
        if use_llm and index < len(questions) - 1 and not outcomes[-1].refused_before_llm:
            time.sleep(LLM_PAUSE_SECONDS)

    print(report(outcomes, use_llm=use_llm))

    if args.verbose:
        print(verbose_table(outcomes))

    if args.json_out:
        payload = {
            "config": {
                "chunks": collection.count(),
                "top_k": config.top_k,
                "similarity_floor": config.similarity_floor,
                "chunk_size": config.chunk_size,
                "answer_model": config.answer_model,
                "llm": use_llm,
            },
            "questions": [
                {
                    "id": o.id,
                    "question": o.question,
                    "type": o.type,
                    "expected": o.expected,
                    "ranked_articles": o.ranked_articles[:10],
                    "top_1": o.top_1,
                    "top_5": o.top_5,
                    "answer_correct": o.answer_correct,
                    "refused": o.refused,
                    "refused_before_llm": o.refused_before_llm,
                    "missing_tokens": o.missing_tokens,
                    "best_similarity": o.best_similarity,
                    "answer": o.answer,
                    "error": o.error,
                }
                for o in outcomes
            ],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")

    # Exit 0 whether the score is good or bad: this is a measurement, not a
    # gate. A non-zero exit is reserved for "the measurement could not run".
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
