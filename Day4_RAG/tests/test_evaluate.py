"""Tests for the evaluation harness.

The harness is what justifies SIMILARITY_FLOOR, so its scoring has to be right
or the justification is worthless. These tests use hand-built retrieval results
rather than a real corpus: the question here is "does it score correctly",
not "does the corpus retrieve well".
"""

import json

import pytest

from app.config import Config
from app.evaluate import (
    QuestionOutcome,
    SweepPoint,
    evaluate_at,
    format_sweep,
    load_questions,
)
from app.retriever import RetrievalResult, RetrievedChunk


def make_chunk(title: str, similarity: float) -> RetrievedChunk:
    return RetrievedChunk(
        text="body",
        similarity=similarity,
        document_id=1,
        document_title=title,
        document_url="https://example.com/1",
        document_source="example.com",
        heading="",
    )


def make_result(query: str, scored: list[tuple[str, float]]) -> RetrievalResult:
    """A retrieval result with the floor disabled, as the sweep produces."""
    chunks = [make_chunk(t, s) for t, s in scored]
    return RetrievalResult(query=query, accepted=chunks, rejected=[], floor=-1.0)


# --------------------------------------------------------------------------
# Scoring one question.
# --------------------------------------------------------------------------


def test_answerable_question_is_correct_when_expected_article_retrieved():
    outcome = QuestionOutcome(
        question="q",
        answerable=True,
        best_similarity=0.8,
        retrieved_titles=["Right Article", "Other"],
        expected_titles=["Right Article"],
    )
    assert outcome.correct


def test_answerable_question_is_wrong_when_a_different_article_retrieved():
    # Retrieving SOMETHING is not success. An answer built on the wrong
    # article is confidently wrong, which is worse than a refusal.
    outcome = QuestionOutcome(
        question="q",
        answerable=True,
        best_similarity=0.8,
        retrieved_titles=["Wrong Article"],
        expected_titles=["Right Article"],
    )
    assert not outcome.correct


def test_answerable_question_is_wrong_when_refused():
    outcome = QuestionOutcome(
        question="q",
        answerable=True,
        best_similarity=0.1,
        retrieved_titles=[],
        expected_titles=["Right Article"],
    )
    assert not outcome.correct


def test_unanswerable_question_is_correct_only_when_refused():
    refused = QuestionOutcome(
        question="q", answerable=False, best_similarity=0.1, retrieved_titles=[]
    )
    answered = QuestionOutcome(
        question="q", answerable=False, best_similarity=0.9,
        retrieved_titles=["Some Article"],
    )
    assert refused.correct
    assert not answered.correct


# --------------------------------------------------------------------------
# Sweeping the floor.
# --------------------------------------------------------------------------


@pytest.fixture
def results():
    """Two answerable questions and two unanswerable, with known scores."""
    return {
        "a1": (make_result("a1", [("Article A", 0.80)]), True, ["Article A"]),
        "a2": (make_result("a2", [("Article B", 0.45)]), True, ["Article B"]),
        "u1": (make_result("u1", [("Article A", 0.20)]), False, []),
        "u2": (make_result("u2", [("Article C", 0.55)]), False, []),
    }


def test_low_floor_gives_perfect_recall_and_zero_refusal(results):
    # THE DEGENERATE CASE THE TWO-RATE DESIGN EXISTS TO EXPOSE. A floor this
    # low answers everything, which scores 100% on answerable questions while
    # being useless -- visible only because the refusal rate is reported too.
    point = evaluate_at(0.10, results)
    assert point.recall == 1.0
    assert point.refusal_rate == 0.0
    assert point.false_answer_rate == 1.0


def test_high_floor_refuses_everything_including_answerable(results):
    point = evaluate_at(0.99, results)
    assert point.recall == 0.0
    assert point.refusal_rate == 1.0


def test_intermediate_floor_trades_one_against_the_other(results):
    # At 0.50: a1 (0.80) retrieved, a2 (0.45) lost; u1 (0.20) refused,
    # u2 (0.55) not.
    point = evaluate_at(0.50, results)
    assert point.recall == 0.5
    assert point.refusal_rate == 0.5


def test_false_answer_rate_is_the_complement_of_refusal(results):
    for floor in (0.1, 0.3, 0.5, 0.9):
        point = evaluate_at(floor, results)
        assert point.false_answer_rate == pytest.approx(1 - point.refusal_rate)


def test_recall_is_monotonically_non_increasing_as_the_floor_rises(results):
    # Raising the floor can only remove chunks, never add them, so recall
    # cannot improve. A violation would mean the filter is applied wrongly.
    floors = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    recalls = [evaluate_at(f, results).recall for f in floors]
    assert all(a >= b for a, b in zip(recalls, recalls[1:]))


def test_refusal_rate_is_monotonically_non_decreasing(results):
    floors = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    rates = [evaluate_at(f, results).refusal_rate for f in floors]
    assert all(a <= b for a, b in zip(rates, rates[1:]))


def test_sweep_table_renders_every_floor(results):
    points = [evaluate_at(f, results) for f in (0.2, 0.4, 0.6)]
    table = format_sweep(points)
    assert "0.200" in table and "0.400" in table and "0.600" in table
    assert "best balanced" in table


# --------------------------------------------------------------------------
# The question set itself.
# --------------------------------------------------------------------------


def test_question_set_requires_both_kinds(tmp_path, monkeypatch):
    # A set with only answerable questions would let a floor of -1 score
    # perfectly, producing a "measured" threshold that is measuring nothing.
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"answerable": [{"question": "q"}]}), encoding="utf-8")
    monkeypatch.setenv("EVAL_QUESTIONS_PATH", str(path))

    with pytest.raises(ValueError) as exc:
        load_questions(Config())
    assert "unanswerable" in str(exc.value)


def test_missing_question_set_is_reported_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_QUESTIONS_PATH", str(tmp_path / "absent.json"))
    with pytest.raises(FileNotFoundError):
        load_questions(Config())


def test_the_real_question_set_is_valid():
    # Guards the shipped file: every answerable question must name at least
    # one expected source, or it can never be scored as correct.
    config = Config()
    answerable, unanswerable = load_questions(config)

    assert len(answerable) >= 10
    assert len(unanswerable) >= 5
    for item in answerable:
        assert item.get("expect_sources"), f"no expect_sources: {item['question']}"
