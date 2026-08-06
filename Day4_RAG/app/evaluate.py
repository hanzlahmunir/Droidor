"""Measure retrieval quality, and choose the similarity floor from data.

WHY THIS EXISTS. `SIMILARITY_FLOOR` started as 0.35 -- a guess. A guessed
threshold is the weakest part of a system whose headline claim is "it refuses
what it cannot answer", because nobody can say whether it refuses too much,
too little, or by luck. This module replaces the guess with a number chosen
from a measured trade-off.

THE TWO RATES, AND WHY BOTH ARE REQUIRED.

    recall@k       of the questions the corpus CAN answer, how often is the
                   right article retrieved?
    refusal rate   of the questions it CANNOT answer, how often does the
                   system correctly refuse?

Reporting either alone is meaningless, because each is trivially maximised by
breaking the other. Set the floor to -1 and recall is perfect while the system
answers everything, confidently and wrongly. Set it to 1.0 and it refuses
everything, scoring a perfect refusal rate while being useless. Only the pair
says anything, and the floor is the knob that trades one against the other.

WHAT THE SWEEP DOES NOT MEASURE. It scores RETRIEVAL -- whether the right
chunks come back and whether the floor lets them through. It deliberately does
not call the LLM, because that would make a sweep of a dozen thresholds cost
hundreds of model calls and make the numbers depend on sampling. The prompt
layer's contribution is measured separately by `--with-llm`, on the single
chosen floor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Config
from app.embedder import Embedder
from app.retriever import RetrievalResult, retrieve


@dataclass
class QuestionOutcome:
    """What happened for one question at one floor."""

    question: str
    answerable: bool
    best_similarity: float | None
    retrieved_titles: list[str]
    expected_titles: list[str] = field(default_factory=list)

    @property
    def had_evidence(self) -> bool:
        """Did anything clear the floor -- i.e. did the system try to answer?"""
        return self.best_similarity is not None and bool(self.retrieved_titles)

    @property
    def found_expected(self) -> bool:
        """Was a expected article among those retrieved?

        Compared on title because that is what a citation shows a reader. An
        answer citing the right article is the outcome that matters; which
        chunk of it was retrieved is an implementation detail.
        """
        return any(title in self.retrieved_titles for title in self.expected_titles)

    @property
    def correct(self) -> bool:
        """Did the system do the right thing?

        For an answerable question: retrieve the expected article.
        For an unanswerable one: refuse.
        """
        if self.answerable:
            return self.had_evidence and self.found_expected
        return not self.had_evidence


@dataclass
class SweepPoint:
    """Aggregate results at one floor value."""

    floor: float
    answerable_total: int
    answerable_correct: int
    unanswerable_total: int
    unanswerable_refused: int

    @property
    def recall(self) -> float:
        if not self.answerable_total:
            return 0.0
        return self.answerable_correct / self.answerable_total

    @property
    def refusal_rate(self) -> float:
        if not self.unanswerable_total:
            return 0.0
        return self.unanswerable_refused / self.unanswerable_total

    @property
    def false_answer_rate(self) -> float:
        """How often it answered something it should have refused.

        The number that matters most for this system's stated contract: the
        task says the answer must be "I don't know", not a guess.
        """
        return 1.0 - self.refusal_rate

    @property
    def balanced_score(self) -> float:
        """Recall and refusal weighted equally.

        Used only to SUGGEST a floor, never to pick one silently. Equal
        weighting is a value judgement -- a system where a wrong answer is
        costlier than a missed one should weight refusal higher -- so the full
        table is always printed and the suggestion is labelled as such.
        """
        return (self.recall + self.refusal_rate) / 2


def load_questions(config: Config) -> tuple[list[dict], list[dict]]:
    """Read the evaluation set, failing clearly if it is absent or malformed."""
    path = Path(config.eval_questions_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No evaluation set at {path}. It defines what 'correct' means "
            f"and cannot be inferred from the corpus."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    answerable = data.get("answerable", [])
    unanswerable = data.get("unanswerable", [])

    if not answerable or not unanswerable:
        # A set with only one kind cannot measure the trade-off, and would
        # produce a floor optimised for half the problem.
        raise ValueError(
            "The evaluation set needs BOTH answerable and unanswerable "
            "questions. Measuring only one lets a broken floor score "
            "perfectly -- see the module docstring."
        )

    return answerable, unanswerable


def evaluate_at(
    floor: float,
    results: dict[str, tuple[RetrievalResult, bool, list[str]]],
) -> SweepPoint:
    """Score pre-computed retrievals at one floor.

    Retrieval is run ONCE per question and re-scored at every floor, rather
    than re-querying per threshold. The floor is a filter applied after the
    search, so re-embedding for each trial would multiply the cost by the
    number of trials and could not change the outcome.
    """
    answerable_total = answerable_correct = 0
    unanswerable_total = unanswerable_refused = 0

    for _, (result, answerable, expected) in results.items():
        all_chunks = result.accepted + result.rejected
        passing = [c for c in all_chunks if c.similarity >= floor]
        titles = [c.document_title for c in passing]

        outcome = QuestionOutcome(
            question=result.query,
            answerable=answerable,
            best_similarity=result.best_similarity,
            retrieved_titles=titles,
            expected_titles=expected,
        )

        if answerable:
            answerable_total += 1
            answerable_correct += int(outcome.correct)
        else:
            unanswerable_total += 1
            unanswerable_refused += int(outcome.correct)

    return SweepPoint(
        floor=floor,
        answerable_total=answerable_total,
        answerable_correct=answerable_correct,
        unanswerable_total=unanswerable_total,
        unanswerable_refused=unanswerable_refused,
    )


def run_retrievals(
    config: Config,
    embedder: Embedder,
    answerable: list[dict],
    unanswerable: list[dict],
    *,
    collection=None,
) -> dict[str, tuple[RetrievalResult, bool, list[str]]]:
    """Retrieve once per question, with the floor effectively disabled.

    floor=-1.0 accepts everything, so the raw scores are available and every
    threshold can be scored afterwards from the same data.
    """
    results: dict[str, tuple[RetrievalResult, bool, list[str]]] = {}

    for item in answerable:
        question = item["question"]
        results[question] = (
            retrieve(question, config, embedder, collection=collection, floor=-1.0),
            True,
            item.get("expect_sources", []),
        )

    for item in unanswerable:
        question = item["question"]
        results[question] = (
            retrieve(question, config, embedder, collection=collection, floor=-1.0),
            False,
            [],
        )

    return results


def sweep(
    config: Config,
    embedder: Embedder,
    *,
    floors: list[float] | None = None,
    collection=None,
) -> tuple[list[SweepPoint], dict[str, tuple[RetrievalResult, bool, list[str]]]]:
    """Score every candidate floor over the whole question set."""
    answerable, unanswerable = load_questions(config)
    results = run_retrievals(
        config, embedder, answerable, unanswerable, collection=collection
    )

    if floors is None:
        floors = [round(0.20 + 0.025 * i, 3) for i in range(19)]  # 0.200 .. 0.650

    return [evaluate_at(f, results) for f in floors], results


def format_sweep(points: list[SweepPoint]) -> str:
    """The trade-off table. Printed in full so the choice is inspectable."""
    lines = [
        "  floor   recall   refusal   false-answer   balanced",
        "  -----   ------   -------   ------------   --------",
    ]
    best = max(points, key=lambda p: p.balanced_score) if points else None

    for point in points:
        marker = " <-- best balanced" if point is best else ""
        lines.append(
            f"  {point.floor:5.3f}   "
            f"{point.recall:6.1%}   "
            f"{point.refusal_rate:7.1%}   "
            f"{point.false_answer_rate:12.1%}   "
            f"{point.balanced_score:8.1%}{marker}"
        )
    return "\n".join(lines)


def describe_failures(
    floor: float,
    results: dict[str, tuple[RetrievalResult, bool, list[str]]],
) -> str:
    """The questions the system gets wrong at the chosen floor.

    Aggregate rates say how well it does; this says WHAT it gets wrong, which
    is the part that suggests the next fix. Day 3's report did the same by
    listing the five shortest articles rather than only the mean length.
    """
    misses: list[str] = []
    false_answers: list[str] = []

    for question, (result, answerable, expected) in results.items():
        passing = [
            c for c in result.accepted + result.rejected if c.similarity >= floor
        ]
        titles = [c.document_title for c in passing]
        best = result.best_similarity

        if answerable:
            if not titles:
                misses.append(
                    f"    REFUSED (best {best:.3f}): {question[:66]}"
                )
            elif not any(t in titles for t in expected):
                misses.append(
                    f"    WRONG ARTICLE (best {best:.3f}): {question[:56]}\n"
                    f"        expected: {expected[0][:60] if expected else '?'}\n"
                    f"        got:      {titles[0][:60]}"
                )
        else:
            if titles:
                false_answers.append(
                    f"    ANSWERED (best {best:.3f}): {question[:66]}\n"
                    f"        would cite: {titles[0][:60]}"
                )

    sections = []
    if misses:
        sections.append("  Answerable questions handled wrongly:\n" + "\n".join(misses))
    if false_answers:
        sections.append(
            "  Unanswerable questions NOT refused by the floor\n"
            "  (these reach the LLM, where the prompt is the second layer):\n"
            + "\n".join(false_answers)
        )
    if not sections:
        sections.append("  No failures at this floor.")

    return "\n\n".join(sections)
