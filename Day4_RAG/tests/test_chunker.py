"""Tests for the chunker.

Offline by construction: the chunker is pure functions over strings, so there
is no database, no network and no model here. Every test states a property the
retrieval half depends on, rather than pinning exact output -- a test that
asserts "produces 7 chunks" breaks on every tuning change and tells you
nothing about whether the chunker is still correct.
"""

import os

import pytest

from app.chunker import Chunk, chunk_markdown, _split_into_blocks, _split_into_sections
from app.config import Config

CODE_FENCE = "`" * 3


def make_config(**overrides: object) -> Config:
    """A Config with the given environment overrides, restored afterwards."""
    previous = {}
    for key, value in overrides.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = str(value)
    try:
        return Config()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def chunk(text: str, **overrides: object) -> list[Chunk]:
    return chunk_markdown(
        text,
        document_id=1,
        document_title="Test Article",
        document_url="https://example.com/a",
        document_source="example.com",
        config=make_config(**overrides),
    )


# --------------------------------------------------------------------------
# Code blocks stay whole. This is the property Day 3 paid for and the one a
# naive fixed-size chunker destroys.
# --------------------------------------------------------------------------


def test_code_block_is_not_split_across_chunks():
    code = "\n".join(f"line_{i} = compute({i})" for i in range(20))
    text = f"""## Setup

Some prose introducing the example.

{CODE_FENCE}
{code}
{CODE_FENCE}

Some prose after it."""

    chunks = chunk(text, CHUNK_SIZE=400, MIN_CHUNK_CHARS=20)

    # The fences must be balanced in every chunk that contains one. An odd
    # count means a block was cut in half, leaving an unterminated fence.
    for c in chunks:
        assert c.text.count(CODE_FENCE) % 2 == 0, (
            f"chunk has unbalanced code fences:\n{c.text}"
        )

    # And the code itself must survive intact in exactly one chunk.
    holders = [c for c in chunks if "line_0 = compute(0)" in c.text]
    assert len(holders) == 1
    assert "line_19 = compute(19)" in holders[0].text


def test_blank_line_inside_code_block_is_not_a_paragraph_break():
    text = f"""## Example

{CODE_FENCE}
def a():
    pass

def b():
    pass
{CODE_FENCE}
"""
    blocks = _split_into_blocks(text.split("## Example")[1])
    code_blocks = [b for b in blocks if b.is_code]
    assert len(code_blocks) == 1
    assert "def a()" in code_blocks[0].text
    assert "def b()" in code_blocks[0].text


def test_oversized_code_block_is_split_rather_than_swallowing_everything():
    # Above MAX_CODE_BLOCK_CHARS the whole-block exemption is withdrawn, or a
    # single huge block would crowd out every other result.
    body = "\n".join(f"x{i} = {i}" for i in range(400))
    text = f"## Big\n\n{CODE_FENCE}\n{body}\n{CODE_FENCE}\n"

    chunks = chunk(text, CHUNK_SIZE=500, MAX_CODE_BLOCK_CHARS=1000, MIN_CHUNK_CHARS=20)

    assert len(chunks) > 1
    assert all(len(c.text) <= 1200 for c in chunks)


def test_hash_inside_code_block_is_not_treated_as_a_heading():
    # A shell comment or CSS id selector. Treating it as a heading would split
    # the code block apart -- the exact damage this module exists to prevent.
    text = f"""## Real Heading

{CODE_FENCE}
# this is a shell comment, not a heading
echo hello
{CODE_FENCE}
"""
    sections = _split_into_sections(text)
    assert len(sections) == 1
    assert sections[0][0] == "Real Heading"
    assert "shell comment" in sections[0][1]


# --------------------------------------------------------------------------
# Headings: the context prefix that makes a chunk retrievable.
# --------------------------------------------------------------------------


def test_chunk_carries_its_heading_into_the_embedded_text():
    text = """## dict.get()

It returns None if the key is missing, rather than raising KeyError.
This is the behaviour people rely on when reading optional config values."""

    chunks = chunk(text)
    assert chunks
    assert chunks[0].heading == "dict.get()"
    # The heading must be part of what gets embedded, or the chunk embeds as
    # context-free text and is not findable by a question naming the method.
    assert "dict.get()" in chunks[0].embeddable_text()


def test_nested_headings_keep_their_parent_trail():
    text = """# Performance

Intro text that is long enough to survive the minimum chunk length filter.

## Caching

Cache entries expire after sixty seconds by default in this system."""

    chunks = chunk(text, MIN_CHUNK_CHARS=20)
    cache_chunks = [c for c in chunks if "expire" in c.text]
    assert cache_chunks
    # Without the parent, "Caching" alone is too terse to disambiguate.
    assert cache_chunks[0].heading == "Performance > Caching"


def test_sibling_heading_replaces_rather_than_nests():
    text = """## First

Body of the first section, long enough to be kept by the length filter.

## Second

Body of the second section, also long enough to be kept by the filter."""

    chunks = chunk(text, MIN_CHUNK_CHARS=20)
    headings = {c.heading for c in chunks}
    assert headings == {"First", "Second"}


def test_heading_trail_survives_a_skipped_level():
    # "#" straight to "###" with no "##" between. Real articles do this
    # constantly. A trail indexed by list POSITION rather than heading LEVEL
    # mis-nests here, which is the bug this pair of tests caught.
    text = """# Top

Introductory body text that is long enough to survive the length filter.

### Deep

Body of the deeply nested section, also long enough to be kept."""

    chunks = chunk(text, MIN_CHUNK_CHARS=20)
    deep = [c for c in chunks if "deeply nested" in c.text]
    assert deep
    assert deep[0].heading == "Top > Deep"


def test_returning_to_a_shallower_level_drops_the_deeper_trail():
    text = """# Alpha

Body under alpha, long enough to be kept by the minimum length filter.

## Beta

Body under beta, long enough to be kept by the minimum length filter.

# Gamma

Body under gamma, long enough to be kept by the minimum length filter."""

    chunks = chunk(text, MIN_CHUNK_CHARS=20)
    gamma = [c for c in chunks if "under gamma" in c.text]
    assert gamma
    # Beta must not linger in the trail once we return to a level-1 heading.
    assert gamma[0].heading == "Gamma"


def test_text_before_any_heading_is_kept():
    # Articles routinely open with prose before the first heading. Dropping it
    # would silently lose the introduction of every such article.
    text = """This opening paragraph comes before any heading at all, and it
contains the thesis of the article, which is exactly what a reader would ask about.

## Later Section

Something else entirely."""

    chunks = chunk(text, MIN_CHUNK_CHARS=20)
    lead = [c for c in chunks if "thesis" in c.text]
    assert lead
    assert lead[0].heading is None


# --------------------------------------------------------------------------
# Sizing and overlap.
# --------------------------------------------------------------------------


def test_chunks_respect_the_size_budget():
    para = " ".join(f"word{i}" for i in range(60))
    text = "\n\n".join([para] * 12)

    chunks = chunk(text, CHUNK_SIZE=500, CHUNK_OVERLAP=50)

    assert len(chunks) > 1
    # Overlap is prepended, so the budget is not a hard ceiling -- but it must
    # not be wildly exceeded either.
    for c in chunks:
        assert len(c.text) <= 500 + 50 + 100


def test_overlap_repeats_text_between_adjacent_chunks():
    sentences = [
        f"Sentence number {i} carries a distinct payload token tok{i} in it."
        for i in range(40)
    ]
    text = "\n\n".join(sentences)

    with_overlap = chunk(text, CHUNK_SIZE=400, CHUNK_OVERLAP=120, MIN_CHUNK_CHARS=20)
    assert len(with_overlap) > 1

    # At least one adjacent pair must share text, or overlap is not happening
    # and a sentence cut at a boundary exists in full in neither chunk.
    shared = False
    for previous, following in zip(with_overlap, with_overlap[1:]):
        tail = previous.text[-120:].strip()
        for token in tail.split():
            if len(token) > 4 and token in following.text:
                shared = True
                break
        if shared:
            break
    assert shared, "no overlap found between any adjacent chunks"


def test_overlap_never_carries_part_of_a_code_block():
    # THE REGRESSION TEST FOR THE BUG THE REAL CORPUS FOUND.
    #
    # Overlap used to be `text[-overlap:]` -- a blind character slice. When a
    # chunk ended with a code block, the tail was the block's interior plus
    # its closing fence, so the next chunk began mid-function with an orphaned
    # "```". Twelve chunks in the real 20-article corpus looked like this,
    # while every unit test passed: the test prose was short enough that the
    # tail never landed inside a fence.
    #
    # The shape below is what the real article had: prose, a code block, then
    # more prose, sized so the packer must break right after the code.
    code = "\n".join(f"    self.value_{i} = compute_something({i})" for i in range(14))
    prose = " ".join(f"word{i}" for i in range(70))
    text = f"""## Query builders

{prose}

{CODE_FENCE}
def build(self):
{code}
{CODE_FENCE}

{prose}

{prose}"""

    chunks = chunk(text, CHUNK_SIZE=600, CHUNK_OVERLAP=150, MIN_CHUNK_CHARS=20)

    for c in chunks:
        assert c.text.count(CODE_FENCE) % 2 == 0, (
            f"overlap carried an unbalanced fence into a chunk:\n{c.text[:300]}"
        )
        # A chunk must never OPEN with code carried over from its predecessor.
        assert not c.text.lstrip().startswith("self.value_"), (
            f"chunk begins mid-code-block:\n{c.text[:200]}"
        )


def test_short_fragments_are_dropped():
    text = """## A

tiny

## B

also tiny"""
    assert chunk(text, MIN_CHUNK_CHARS=80) == []


def test_ordinals_are_sequential_and_in_reading_order():
    para = " ".join(f"word{i}" for i in range(60))
    text = f"## One\n\n{para}\n\n## Two\n\n{para}"

    chunks = chunk(text, CHUNK_SIZE=400, MIN_CHUNK_CHARS=20)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


# --------------------------------------------------------------------------
# Degenerate input: an ingester meets all of this eventually.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n", "#", "##   "])
def test_empty_or_degenerate_input_produces_no_chunks(text):
    assert chunk(text) == []


def test_unterminated_fence_does_not_swallow_the_article():
    # A truncated page or a stray "```" in prose. Treating the remainder as
    # one code block would make the rest of the article unsplittable.
    text = f"""## Heading

{CODE_FENCE}
def broken():
    pass

This prose is after an unterminated fence and must still be chunked normally
rather than being absorbed into a single enormous code block that never ends."""

    chunks = chunk(text, CHUNK_SIZE=200, MIN_CHUNK_CHARS=20)
    assert chunks
    assert any("prose is after" in c.text for c in chunks)


def test_citation_fields_are_copied_onto_every_chunk():
    # A citation must be renderable from the chunk alone -- no join, no second
    # API call, and it must survive the article being deleted from Day 1.
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk(text, CHUNK_SIZE=300)

    assert len(chunks) > 1
    for c in chunks:
        assert c.document_id == 1
        assert c.document_title == "Test Article"
        assert c.document_url == "https://example.com/a"
        assert c.document_source == "example.com"


def test_chunking_is_deterministic():
    # The same article must chunk identically across runs, or content hashes
    # change and re-ingest duplicates the corpus instead of being idempotent.
    text = "\n\n".join(f"Paragraph {i} with enough text to be kept." * 3 for i in range(10))
    assert [c.text for c in chunk(text)] == [c.text for c in chunk(text)]
