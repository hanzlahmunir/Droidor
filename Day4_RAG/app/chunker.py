"""Split an article's Markdown into chunks worth embedding.

WHY NOT FIXED-SIZE WINDOWS. The obvious chunker slices every N characters and
ignores what it is cutting. It is simple, and it is wrong here for a specific
reason: Day 3 went to real trouble to preserve article STRUCTURE -- 139
headings and 46 code blocks across this corpus, with a whole converter
rewritten to stop code indentation being stripped. A blind slicer discards
exactly that, cutting code blocks in half and separating a paragraph from the
heading that says what it is about.

So this splits on the structure that is already there:

  1. Sections, at ATX headings ("## Heading"). Every chunk records the heading
     it came from.
  2. Within a section, paragraphs are packed up to the size budget.
  3. Fenced code blocks are kept whole, even when oversized.

THE HEADING PREFIX IS THE POINT. Each chunk is stored with its heading
prepended, because embeddings have no memory of where text came from. A chunk
reading "It returns None if the key is missing" is nearly meaningless on its
own, and embeds to something generic. The same chunk under "## dict.get()"
embeds close to a question about dict.get. Retrieval quality here comes more
from that prefix than from any threshold tuning.

Everything in this module is a pure function over strings: no database, no
network, no model. That is what makes the whole retrieval half testable
offline, which is the same property Day 3's suite depends on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Config

# ATX headings only ("## Heading"), which is what Day 3's renderer emits --
# it passes heading_style="ATX" to markdownify explicitly. Setext underlines
# are therefore not handled, and that is a deliberate scope decision rather
# than an oversight.
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*$")

# A fence line. Day 3 renders with code_language="" so there is no language
# tag, but the suffix is matched anyway: an article quoting Markdown source
# can contain "```python", and a matcher that only accepted bare fences would
# treat that as prose and split through the middle of the block.
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class Chunk:
    """One unit of retrievable text, with everything a citation needs.

    The document fields are copied onto every chunk rather than referenced by
    id. That denormalisation is deliberate: a citation must be renderable from
    the chunk alone, with no join and no second API call, and it must survive
    the article later being deleted from Day 1. Storage is a few hundred bytes
    per chunk against a corpus of 20 articles -- irrelevant next to a citation
    that cannot be resolved.
    """

    text: str
    heading: str | None
    ordinal: int
    document_id: int
    document_title: str
    document_url: str
    document_source: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    def embeddable_text(self) -> str:
        """The string that actually gets embedded.

        The heading is prepended so the vector carries the section's topic.
        See the module docstring: this is the single highest-leverage decision
        in the chunker.
        """
        if self.heading:
            return f"{self.heading}\n\n{self.text}"
        return self.text


@dataclass(frozen=True)
class _Block:
    """A run of lines that must not be split apart from each other."""

    text: str
    is_code: bool


def _split_into_blocks(section_text: str) -> list[_Block]:
    """Split a section into paragraphs and code blocks.

    Fence tracking is the whole job here. A blank line inside a code block is
    NOT a paragraph break -- code is full of blank lines -- so splitting on
    "\\n\\n" without tracking fences dismembers every code block in the corpus.

    The closing fence must be at least as long as the opening one and of the
    same character, per CommonMark, so that a "```" inside a "~~~~" block does
    not close it early.
    """
    blocks: list[_Block] = []
    buffer: list[str] = []
    fence: str | None = None

    def flush_prose() -> None:
        """Emit whatever prose has accumulated, split on blank lines."""
        if not buffer:
            return
        for para in re.split(r"\n[ \t]*\n", "\n".join(buffer)):
            if para.strip():
                blocks.append(_Block(para.strip("\n"), is_code=False))
        buffer.clear()

    for line in section_text.split("\n"):
        match = _FENCE_RE.match(line)

        if fence is None:
            if match:
                # Opening fence: flush the prose before it, start collecting.
                flush_prose()
                fence = match.group(1)
                buffer.append(line)
            else:
                buffer.append(line)
            continue

        # Inside a code block: everything is literal until the fence closes.
        buffer.append(line)
        if match:
            marker = match.group(1)
            # Same character, and at least as long. `match.group(2)` must be
            # empty -- "```python" opens a block, it never closes one.
            if marker[0] == fence[0] and len(marker) >= len(fence) and not match.group(2).strip():
                blocks.append(_Block("\n".join(buffer), is_code=True))
                buffer.clear()
                fence = None

    if fence is not None:
        # An unterminated fence. Real articles contain them -- a truncated page
        # or a stray "```" in prose. Treating the remainder as code would
        # swallow the rest of the article into one unsplittable block, so it
        # is emitted as prose instead.
        blocks.append(_Block("\n".join(buffer).strip("\n"), is_code=False))
    else:
        flush_prose()

    return [b for b in blocks if b.text.strip()]


def _split_oversized(text: str, config: Config) -> list[str]:
    """Split a single over-long block on sentence, then line, then character.

    Reached when one paragraph exceeds the budget on its own. The ladder tries
    the least damaging cut first: a sentence boundary reads naturally, a line
    boundary is tolerable, a hard character cut is the last resort and only
    happens for text with neither -- a minified blob or a very long URL.
    """
    limit = config.chunk_size
    if len(text) <= limit:
        return [text]

    # Sentence-ish boundaries: terminator followed by whitespace. Kept simple
    # deliberately -- a real sentence tokeniser is a dependency and a model
    # download to solve a problem that only affects where a rare long
    # paragraph gets divided.
    pieces = re.split(r"(?<=[.!?])\s+", text)
    if max((len(p) for p in pieces), default=0) > limit:
        pieces = text.split("\n")
    if max((len(p) for p in pieces), default=0) > limit:
        pieces = [text[i : i + limit] for i in range(0, len(text), limit)]

    # Repack the pieces up to the limit so the result is as few chunks as
    # possible rather than one chunk per sentence.
    out: list[str] = []
    current = ""
    for piece in pieces:
        if not piece.strip():
            continue
        candidate = f"{current}\n{piece}" if current else piece
        if len(candidate) > limit and current:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _overlap_tail(text: str, overlap: int) -> str:
    """The tail of a chunk, to prepend to the next one.

    Overlap exists so a sentence spanning a boundary survives intact in at
    least one chunk.

    WHY THIS IS LINE-BASED AND FENCE-AWARE RATHER THAN A CHARACTER SLICE.
    The obvious implementation, `text[-overlap:]`, cuts at an arbitrary offset
    with no idea what it is cutting through. Measured on the real corpus that
    produced 12 chunks with unbalanced code fences: where a chunk ended with a
    code block, the tail was a slice of that block's interior plus its closing
    fence, so the NEXT chunk began mid-function with an orphaned "```". Those
    chunks are unreadable as evidence and would be quoted verbatim into an
    answer.

    Every unit test passed while this was broken, because each one used prose
    short enough that the tail never landed inside a fence. Only running the
    real 20 articles through it showed the failure -- the same lesson as Day 3,
    where the bugs that mattered were the ones only a live run found.

    So: complete lines only, and never any part of a code block.
    """
    if overlap <= 0 or not text:
        return ""

    lines = text.split("\n")

    # Walk backwards over the tail, stopping at a fence. A tail is only useful
    # as context if it is prose the next chunk continues from; code carried
    # across a boundary is noise at best and a broken fragment at worst.
    tail_lines: list[str] = []
    length = 0
    for line in reversed(lines):
        if _FENCE_RE.match(line):
            break
        # +1 for the newline that will rejoin them.
        if length + len(line) + 1 > overlap and tail_lines:
            break
        tail_lines.insert(0, line)
        length += len(line) + 1

    tail = "\n".join(tail_lines).strip()

    # A single line longer than the whole overlap budget: trim it back to a
    # word boundary rather than returning the entire paragraph.
    if len(tail) > overlap:
        tail = tail[-overlap:]
        space = tail.find(" ")
        if 0 <= space < len(tail) - 1:
            tail = tail[space + 1 :]

    return tail.strip()


def chunk_markdown(
    text: str,
    *,
    document_id: int,
    document_title: str,
    document_url: str,
    document_source: str,
    config: Config,
) -> list[Chunk]:
    """Split one article into chunks, in reading order.

    Returns an empty list for an article with no substantial text -- a caller
    ingesting a stub gets nothing rather than a chunk of whitespace.
    """
    sections = _split_into_sections(text)

    chunks: list[Chunk] = []
    ordinal = 0

    for heading, body in sections:
        for piece in _pack_blocks(body, config):
            if len(piece.strip()) < config.min_chunk_chars:
                # Too short to be evidence. Dropped rather than merged into a
                # neighbour: a stray heading or caption embeds to something
                # near-arbitrary and, being short, can score misleadingly high
                # against a short question.
                continue
            chunks.append(
                Chunk(
                    text=piece.strip(),
                    heading=heading,
                    ordinal=ordinal,
                    document_id=document_id,
                    document_title=document_title,
                    document_url=document_url,
                    document_source=document_source,
                )
            )
            ordinal += 1

    return chunks


def _split_into_sections(text: str) -> list[tuple[str | None, str]]:
    """Split Markdown into (heading, body) pairs at ATX headings.

    Fence-aware: a "# " line inside a code block is a shell comment or a CSS
    id selector, not a heading. Both appear in this corpus, and treating them
    as headings would split code blocks apart -- the exact damage this module
    exists to avoid.

    The heading trail is kept ("Parent > Child") so a chunk under "### Caching"
    inside "## Performance" carries both. Without the parent, a deeply nested
    heading is often too terse to be useful context on its own.
    """
    sections: list[tuple[str | None, str]] = []
    # Keyed by heading LEVEL, not by list position. A plain list indexed by
    # position gets this wrong the moment an article skips a level or opens at
    # "##": with trail == ["First"], assigning at index level-1 == 1 appends
    # instead of replacing, so two sibling "##" headings produce
    # "First > Second" -- a trail claiming a nesting that does not exist.
    # Articles in this corpus open at every level from 1 to 4, so this is the
    # normal case rather than an edge one.
    trail: dict[int, str] = {}
    current_heading: str | None = None
    buffer: list[str] = []
    fence: str | None = None

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((current_heading, body))
        buffer.clear()

    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not fence_match.group(2).strip():
                fence = None
            buffer.append(line)
            continue

        if fence is not None:
            buffer.append(line)
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            # Drop any entries at or below this level -- they are siblings or
            # children of the heading just closed, not ancestors of this one --
            # then record this heading at its own level.
            for deeper in [lvl for lvl in trail if lvl >= level]:
                del trail[deeper]
            trail[level] = title
            current_heading = " > ".join(trail[lvl] for lvl in sorted(trail))
        else:
            buffer.append(line)

    flush()

    if not sections:
        body = text.strip()
        return [(None, body)] if body else []
    return sections


def _pack_blocks(section_body: str, config: Config) -> list[str]:
    """Pack a section's blocks into chunks of at most chunk_size characters.

    Code blocks are kept whole even when they exceed the budget: half a code
    block is two invalid fragments, and a reader who retrieves one cannot run
    it or trust it. The exemption is capped by MAX_CODE_BLOCK_CHARS, above
    which a block is split anyway rather than being sent as one enormous chunk
    that would crowd out every other result.
    """
    pieces: list[str] = []
    current = ""

    def push() -> None:
        nonlocal current
        if current.strip():
            pieces.append(current.strip())
        current = ""

    for block in _split_into_blocks(section_body):
        if block.is_code:
            if len(block.text) > config.max_code_block_chars:
                push()
                pieces.extend(_split_oversized(block.text, config))
                continue
            # Whole, even if oversized -- as long as it is under the cap.
            if current and len(current) + len(block.text) + 2 > config.chunk_size:
                push()
            if len(block.text) > config.chunk_size:
                push()
                pieces.append(block.text.strip())
                continue
            current = f"{current}\n\n{block.text}" if current else block.text
            continue

        for part in _split_oversized(block.text, config):
            if current and len(current) + len(part) + 2 > config.chunk_size:
                push()
                # Carry the tail of the previous chunk into this one so a
                # sentence cut at the boundary survives somewhere in full.
                tail = _overlap_tail(pieces[-1] if pieces else "", config.chunk_overlap)
                current = f"{tail}\n\n{part}" if tail else part
            else:
                current = f"{current}\n\n{part}" if current else part

    push()
    return pieces
