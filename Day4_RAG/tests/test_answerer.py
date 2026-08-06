"""Tests for answer generation, citation validation and the refusal.

No network and no API key: the Groq client is replaced by a stub that returns
whatever the test wants. That is the point -- the behaviour worth testing here
is what we do with the model's output, not the model itself.
"""

import pytest

from app.answerer import (
    I_DONT_KNOW,
    Answer,
    AnswerError,
    extract_citation_indices,
    generate_answer,
    looks_like_refusal,
    validate_citations,
)
from app.config import Config
from app.retriever import RetrievedChunk


@pytest.fixture
def config(monkeypatch) -> Config:
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    return Config()


def make_chunk(index: int, text: str = "Body text") -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        similarity=0.8,
        document_id=index,
        document_title=f"Article {index}",
        document_url=f"https://example.com/{index}",
        document_source="example.com",
        heading="",
    )


class StubClient:
    """Stands in for the Groq client. Records the call, returns a fixed reply."""

    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self._content = content
        self._finish_reason = finish_reason
        self.last_messages = None

        stub = self

        class _Message:
            content = self._content

        class _Choice:
            message = _Message()
            finish_reason = self._finish_reason

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                stub.last_messages = kwargs["messages"]
                return _Response()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


# --------------------------------------------------------------------------
# Citation extraction. Every form this model was OBSERVED to emit.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Answer [1]", {1}),
        ("Answer [1, 2]", {1, 2}),
        ("Answer [1][2]", {1, 2}),
        ("Answer [1] and more [3]", {1, 3}),
        # THE REAL BUG. openai/gpt-oss-120b emits CJK brackets, with and
        # without a line-range suffix, despite the prompt asking for "[1]".
        # A matcher that understood only ASCII dropped every citation from
        # correct, well-sourced answers and labelled them untrustworthy.
        ("Answer 【1】", {1}),
        ("Answer 【1†L1-L4】", {1}),
        ("Answer 【1†L1-L4】【2†L1-L3】", {1, 2}),
        ("Mixed 【1】 and [2]", {1, 2}),
        ("No citations here", set()),
        ("Not a citation [abc]", set()),
    ],
)
def test_extracts_every_observed_citation_form(text, expected):
    assert extract_citation_indices(text) == expected


def test_valid_citations_map_to_their_sources():
    sources = [make_chunk(1), make_chunk(2), make_chunk(3)]
    text, used = validate_citations("Claim [1] and claim [3]", sources)
    assert [c.document_id for c in used] == [1, 3]
    assert text == "Claim [1] and claim [3]"


def test_invented_citation_is_stripped():
    # A citation pointing at a source we never sent is fabricated provenance.
    # It looks like evidence, which is worse than no citation at all.
    sources = [make_chunk(1), make_chunk(2)]
    text, used = validate_citations("Claim [1] and invented [7]", sources)
    assert [c.document_id for c in used] == [1]
    assert "[7]" not in text
    assert "[1]" in text


def test_invented_cjk_citation_is_also_stripped():
    # The stripping path must understand the same forms the extractor does.
    # A literal text.replace("[7]", "") cannot see 【7†L1-L4】, so an invented
    # CJK marker would survive cleaning and be shown as real provenance.
    sources = [make_chunk(1)]
    text, used = validate_citations("Claim 【1】 and invented 【7†L1-L4】", sources)
    assert [c.document_id for c in used] == [1]
    assert "7" not in text


def test_mixed_marker_keeps_its_valid_part():
    sources = [make_chunk(1), make_chunk(2)]
    text, used = validate_citations("Claim [2, 9]", sources)
    assert [c.document_id for c in used] == [2]
    assert "2" in text and "9" not in text


# --------------------------------------------------------------------------
# The refusal.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I don't know.",
        "I don't know",
        "i don't know.",
        "I do not know.",
        "I don’t know.",  # curly apostrophe
    ],
)
def test_refusal_is_recognised_despite_formatting_variation(text):
    # Models vary punctuation and capitalisation even when told to reply
    # exactly, so `eval` would under-count refusals on a strict comparison.
    assert looks_like_refusal(text)


@pytest.mark.parametrize(
    "text",
    [
        "I don't know much about X, but the answer is Y.",
        "The sources say the answer is 42.",
    ],
)
def test_real_answers_are_not_mistaken_for_refusals(text):
    assert not looks_like_refusal(text)


def test_no_chunks_refuses_without_calling_the_model(config):
    answer = generate_answer("q", [], config)
    assert answer.refused
    assert answer.refused_before_llm
    assert answer.text == I_DONT_KNOW


def test_model_abstention_is_recorded_as_a_distinct_layer(config):
    # Chunks cleared the floor, so this is the PROMPT layer refusing rather
    # than the threshold. `eval` reports which layer caught what.
    client = StubClient("I don't know.")
    answer = generate_answer("q", [make_chunk(1)], config, client=client)

    assert answer.refused
    assert answer.refused_before_llm is False


def test_successful_answer_carries_its_citations(config):
    client = StubClient("The answer is 42 [1].")
    answer = generate_answer("q", [make_chunk(1), make_chunk(2)], config, client=client)

    assert not answer.refused
    assert len(answer.citations) == 1
    assert answer.cited_sources == ["Article 1 (https://example.com/1)"]


def test_repeated_citation_of_one_article_is_listed_once(config):
    client = StubClient("Claim [1] and another claim [2].")
    chunks = [make_chunk(1), make_chunk(1)]  # two chunks, same article
    answer = generate_answer("q", chunks, config, client=client)
    assert len(answer.cited_sources) == 1


# --------------------------------------------------------------------------
# The measured failure mode: a reasoning model that spends its whole budget.
# --------------------------------------------------------------------------


def test_empty_content_from_exhausted_budget_is_an_error_not_a_blank_answer(config):
    # MEASURED, NOT HYPOTHETICAL. openai/gpt-oss-120b writes to a hidden
    # `reasoning` field before `content`. At max_tokens=100 it returned
    # finish_reason='length' with content EMPTY. Rendering that would show the
    # user a blank answer as though the model had nothing to say.
    client = StubClient("", finish_reason="length")
    with pytest.raises(AnswerError) as exc:
        generate_answer("q", [make_chunk(1)], config, client=client)
    assert "ANSWER_MAX_TOKENS" in str(exc.value)


def test_empty_content_for_another_reason_still_errors(config):
    client = StubClient("", finish_reason="stop")
    with pytest.raises(AnswerError):
        generate_answer("q", [make_chunk(1)], config, client=client)


def test_missing_api_key_names_the_missing_key(config, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    keyless = Config()
    with pytest.raises(AnswerError) as exc:
        generate_answer("q", [make_chunk(1)], keyless)
    assert "GROQ_API_KEY" in str(exc.value)


def test_sources_are_numbered_in_the_prompt(config):
    client = StubClient("Answer [1].")
    generate_answer("q", [make_chunk(1), make_chunk(2)], config, client=client)

    user_message = client.last_messages[-1]["content"]
    assert "[1] Article 1" in user_message
    assert "[2] Article 2" in user_message


def test_system_prompt_demands_the_exact_refusal_string(config):
    client = StubClient("Answer [1].")
    generate_answer("q", [make_chunk(1)], config, client=client)

    system_message = client.last_messages[0]["content"]
    # The prompt and the code must agree on the refusal wording, or `eval`
    # counts a refusal as an answer.
    assert I_DONT_KNOW in system_message
