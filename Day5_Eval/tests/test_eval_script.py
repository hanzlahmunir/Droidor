"""Tests for the Day 5 scoring harness (eval.py).

WHY THIS IS TESTED AT ALL. eval.py produces the number the rest of the week is
compared against. A scoring bug does not crash -- it prints a plausible number
that is wrong, and every later decision inherits the error. That failure mode
is silent, which makes it exactly the kind worth pinning down.

The first baseline run proved the point: three of my four "unanswerable"
questions were answerable, and the normaliser was scoring correct answers
wrong over a Unicode hyphen. Both were ground-truth/scoring bugs, not system
bugs, and both looked like a low score rather than an error.

Nothing here touches Chroma, the corpus, or an LLM. The question under test is
"does it score correctly", not "does retrieval work".
"""

from __future__ import annotations

import json

import pytest

import eval as eval_script
from eval import Outcome, check_corpus_drift, missing, normalise, rank_articles, report


class FakeChunk:
    """Enough of a RetrievedChunk for ranking: an id and a score."""

    def __init__(self, document_id: int, similarity: float) -> None:
        self.document_id = document_id
        self.similarity = similarity


class TestRankArticles:
    def test_collapses_chunks_to_distinct_articles(self):
        """Five chunks of one article must not fill five ranking slots.

        This is the whole reason ranking happens over articles: without the
        collapse, "top-5" would be satisfied by one article's chunks and the
        metric would flatter the system.
        """
        chunks = [FakeChunk(7, 0.9), FakeChunk(7, 0.8), FakeChunk(7, 0.7), FakeChunk(3, 0.6)]
        assert rank_articles(chunks) == [7, 3]

    def test_article_takes_the_rank_of_its_best_chunk(self):
        chunks = [FakeChunk(2, 0.4), FakeChunk(5, 0.9), FakeChunk(2, 0.95)]
        assert rank_articles(chunks) == [2, 5]

    def test_empty(self):
        assert rank_articles([]) == []


class TestNormalise:
    @pytest.mark.parametrize(
        "answer, token",
        [
            ("the workers' 5‑second write timeout", "5 second"),
            ("a buffer of about 8 KB", "8KB"),
            ("pass --line‑buffered to grep", "--line-buffered"),
            ("VACUUM  INTO the file", "vacuum into"),
        ],
    )
    def test_typography_does_not_fail_a_correct_answer(self, answer, token):
        """Every case here is a real false negative from the first run.

        U+2011 (non-breaking hyphen) and a spaced "8 KB" render identically to
        the forms in must_contain and mean the same thing. Scoring them wrong
        would measure the model's typography, not its correctness.
        """
        assert missing([token], answer) == []

    def test_still_rejects_a_genuinely_absent_token(self):
        """The normaliser is aggressive; it must not match everything."""
        assert missing(["ANALYZE"], "the author ran VACUUM on the database") == ["ANALYZE"]


class TestMissing:
    def test_nested_list_is_or(self):
        assert missing([["beginning", "front", "start"]], "add it to the front") == []

    def test_nested_list_reports_all_alternatives_when_none_match(self):
        assert missing([["beginning", "front"]], "somewhere else") == ["beginning | front"]

    def test_all_tokens_required(self):
        """A multi question needs a fact from each article, not just one."""
        assert missing(["ANALYZE", "19"], "we ran ANALYZE") == ["19"]

    def test_case_insensitive(self):
        assert missing(["analyze"], "We ran ANALYZE today") == []

    def test_empty_requirements_pass(self):
        assert missing([], "") == []


def _outcome(**kw) -> Outcome:
    base = dict(
        id=1, question="q", type="single", expected=[1], must_contain=[]
    )
    base.update(kw)
    return Outcome(**base)


class TestOutcomeScoring:
    def test_top_1_and_top_5(self):
        o = _outcome(expected=[9], ranked_articles=[3, 4, 5, 9, 2])
        assert not o.top_1
        assert o.top_5

    def test_top_5_is_false_when_outside_the_first_five(self):
        o = _outcome(expected=[9], ranked_articles=[3, 4, 5, 6, 7, 9])
        assert not o.top_5

    def test_multi_matches_on_any_expected_article(self):
        o = _outcome(expected=[23, 1], ranked_articles=[1, 8])
        assert o.top_1

    def test_a_refusal_is_never_a_correct_answer(self):
        """Even with no missing tokens -- "I don't know" contains nothing."""
        o = _outcome(answer="I don't know", refused=True, missing_tokens=[])
        assert not o.answer_correct

    def test_answer_correct_requires_text(self):
        assert not _outcome(answer="", missing_tokens=[]).answer_correct

    def test_unanswerable_sits_out_of_retrieval_scoring(self):
        assert not _outcome(expected=[]).scored_for_retrieval
        assert _outcome(expected=[2]).scored_for_retrieval


class TestReport:
    def test_prints_exactly_five_lines_in_the_required_order(self):
        outcomes = [
            _outcome(id=1, expected=[1], ranked_articles=[1], answer="x", missing_tokens=[]),
            _outcome(id=2, expected=[], type="unanswerable", refused=True),
        ]
        lines = report(outcomes, use_llm=True).splitlines()
        assert len(lines) == 5
        assert lines[0].startswith("Questions:")
        assert lines[1].startswith("Top-1 correct:")
        assert lines[2].startswith("Top-5 correct:")
        assert lines[3].startswith("Answer correct:")
        assert lines[4].startswith("Refused correctly:")

    def test_denominators_exclude_unanswerable_from_retrieval(self):
        """16 answerable + 4 unanswerable must read as /16 and /4, not /20."""
        outcomes = [
            _outcome(id=i, expected=[i], ranked_articles=[i], answer="x", missing_tokens=[])
            for i in range(1, 17)
        ] + [
            _outcome(id=i, expected=[], type="unanswerable", refused=True)
            for i in range(17, 21)
        ]
        text = report(outcomes, use_llm=True)
        assert "Questions:         20" in text
        assert "16/16" in text
        assert "Refused correctly:  4/4" in text

    def test_no_llm_suppresses_the_answer_line_rather_than_printing_zero(self):
        """A skipped measurement must not read as a failed one."""
        text = report([_outcome(expected=[1], ranked_articles=[1])], use_llm=False)
        assert "Answer correct:    -- (--no-llm)" in text
        assert len(text.splitlines()) == 5


class FakeArticle:
    def __init__(self, id: int, title: str) -> None:
        self.id = id
        self.title = title


class TestCorpusDrift:
    """The guard against ground truth that has quietly gone stale.

    `expect_article_ids` are database ids. A re-crawl renumbers them, nothing
    raises, and every question is scored against the wrong article -- a
    confident number that means nothing. Article 113 really did disappear from
    the corpus between the baseline run and the next day, so this is not
    hypothetical.
    """

    @staticmethod
    def _patch(monkeypatch, articles):
        monkeypatch.setattr(eval_script, "load_articles", lambda config: articles)

    def test_no_problems_when_titles_still_match(self, monkeypatch):
        self._patch(monkeypatch, [FakeArticle(2, "Running SQLite")])
        questions = [{"id": 1, "_titles": {"2": "Running SQLite"}}]
        assert check_corpus_drift(questions, None) == []

    def test_detects_a_renumbered_id(self, monkeypatch):
        self._patch(monkeypatch, [FakeArticle(2, "Something Else Entirely")])
        questions = [{"id": 1, "_titles": {"2": "Running SQLite"}}]
        problems = check_corpus_drift(questions, None)
        assert len(problems) == 1
        assert "Q1" in problems[0] and "Running SQLite" in problems[0]

    def test_detects_an_article_that_vanished(self, monkeypatch):
        self._patch(monkeypatch, [FakeArticle(5, "Unrelated")])
        questions = [{"id": 3, "_titles": {"113": "<antirez>"}}]
        problems = check_corpus_drift(questions, None)
        assert len(problems) == 1
        assert "gone" in problems[0]

    def test_a_later_correct_claim_cannot_mask_an_earlier_wrong_one(self, monkeypatch):
        """REGRESSION. This bug shipped and was caught by deliberate corruption.

        Article 2 is referenced by both Q1 and Q9. The first implementation
        flattened every question's `_titles` into one dict keyed by article
        id, so Q9's correct entry overwrote Q1's corrupted one and the guard
        reported "no drift" on an eval set that had drifted -- the guard
        against silent wrong numbers, failing silently and wrongly.
        """
        self._patch(monkeypatch, [FakeArticle(2, "Running SQLite")])
        questions = [
            {"id": 1, "_titles": {"2": "A Totally Different Article"}},
            {"id": 9, "_titles": {"2": "Running SQLite"}},
        ]
        problems = check_corpus_drift(questions, None)
        assert problems, "a wrong claim on Q1 must not be masked by Q9"
        assert "Q1" in problems[0]

    def test_no_titles_recorded_means_no_check(self, monkeypatch):
        """Absent metadata must not be reported as drift."""
        self._patch(monkeypatch, [FakeArticle(1, "x")])
        assert check_corpus_drift([{"id": 1}], None) == []

    def test_an_unreachable_api_is_reported_not_raised(self, monkeypatch):
        def boom(config):
            raise eval_script.CorpusError("connection refused")

        monkeypatch.setattr(eval_script, "load_articles", boom)
        problems = check_corpus_drift([{"id": 1, "_titles": {"2": "x"}}], None)
        assert len(problems) == 1
        assert "could not verify" in problems[0]


class TestEvalSet:
    """The question file is data, and wrong data scores wrongly and silently."""

    @pytest.fixture(scope="class")
    def questions(self):
        return eval_script.load_eval_set()

    def test_has_twenty_questions_with_unique_sequential_ids(self, questions):
        assert len(questions) == 20
        assert [q["id"] for q in questions] == list(range(1, 21))

    def test_composition_matches_the_task(self, questions):
        counts = {}
        for q in questions:
            counts[q["type"]] = counts.get(q["type"], 0) + 1
        assert counts == {"single": 7, "multi": 6, "unanswerable": 4, "vague": 3}

    def test_unanswerable_have_no_expected_articles_and_no_required_tokens(self, questions):
        for q in questions:
            if q["type"] == "unanswerable":
                assert not q["expect_article_ids"], q["id"]
                assert not q["must_contain"], q["id"]

    def test_answerable_have_both_an_article_and_something_to_check(self, questions):
        """A question with no must_contain would score "correct" for free."""
        for q in questions:
            if q["type"] != "unanswerable":
                assert q["expect_article_ids"], q["id"]
                assert q["must_contain"], q["id"]

    def test_every_expected_id_has_a_recorded_title(self, questions):
        """Otherwise the drift guard silently skips that id.

        The check only verifies ids it has a title for, so an id missing from
        `_titles` is unguarded -- and unguarded is indistinguishable from
        verified in the output.
        """
        for q in questions:
            titles = q.get("_titles", {})
            for article_id in q["expect_article_ids"]:
                assert str(article_id) in titles, f"Q{q['id']} id {article_id}"
