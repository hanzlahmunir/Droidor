"""Article extraction and quality scoring.

TWO EXTRACTORS, ON PURPOSE.

trafilatura is the primary. It is the current state of the art for
boilerplate removal and is what extraction benchmarks measure against.
Hand-written BeautifulSoup rules ("delete <nav>, delete .sidebar") were
rejected: they are per-site, and they rot the first time a site is
redesigned.

readability-lxml runs SECOND on the same HTML, using a genuinely different
algorithm (text-density scoring rather than trafilatura's DOM heuristics).
We do not use its output. We use its LENGTH, as a cross-check.

The reason is that the task asks for "% of pages where extraction failed or
returned junk" -- a real number. With one extractor there is nothing to
compare against, so "junk" could only be asserted. With two independent
algorithms, sharp disagreement on length is EVIDENCE: if one returns 4,000
characters and the other 300, at least one of them latched onto the wrong
subtree, and the result should not be trusted. That converts a guess into a
measurement, which is the whole point of the day.

THE QUALITY RULES ARE EXPLICIT AND NAMED. Each rejection records which rule
fired, so "% junk" decomposes by cause instead of being one opaque figure.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import trafilatura
from bs4 import BeautifulSoup
from readability import Document as ReadabilityDocument

from app.config import Config

# Collapses runs of whitespace. Extractors leave ragged spacing where inline
# tags were removed, and unnormalised text would make two otherwise identical
# articles hash differently -- breaking exact-duplicate detection.
_WHITESPACE_RE = re.compile(r"[ \t ]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")

# Boilerplate that survives extraction on some sites. Matched per-line so a
# whole line is dropped, not a substring mid-sentence.
# Markdown line prefixes to look past before matching boilerplate.
#
# Needed because the extractor now emits Markdown: a share widget that used to
# arrive as "Share this" can now arrive as "### Share this" or "- Share this",
# and a pattern anchored on ^\s* would no longer match it. Rather than edit
# twenty patterns, every pattern is prefixed with this once.
#
# Note it does NOT skip "```" -- boilerplate matching must never reach inside
# a code fence, where "advertisement" could be a legitimate variable name.
_MD_PREFIX = r"^\s*(?:#{1,6}\s*|[-*+]\s+|>\s*)?"

_BOILERPLATE_LINE_PATTERNS = tuple(
    re.compile(_MD_PREFIX + pattern, re.I)
    for pattern in (
        r"share (this|on)\b",
        r"(tweet|share|pin it|email this)\s*$",
        r"subscribe to (our|the) newsletter",
        r"sign up for (our|the) newsletter",
        r"(read|related|you might also like|more from|recommended)[\s:]*$",
        # Headings that introduce a trailing list of other posts. Matched as a
        # whole line so an article whose prose mentions "recent articles" is
        # untouched. See strip_trailing_link_list below, which uses these as
        # the cut point.
        r"(recent|latest|popular|previous|other) (articles?|posts?|stories)\s*:?\s*$",
        r"more (articles?|posts?)\b.*$",
        r"(previous|next) (post|article)\b",
        r"posted in\b.*$",
        r"tags?:\s*$",
        r"\d+ (comments?|min read)\s*$",
        r"(copyright|©)\s*\d{4}",
        r"all rights reserved",
        r"cookie (policy|settings|preferences)\s*$",
        r"accept (all )?cookies\s*$",
        r"advertisement\s*$",
        r"loading\.{0,3}\s*$",
    )
)


@dataclass
class ExtractionResult:
    """Everything the pipeline and the report need about one extraction."""

    ok: bool
    text: str = ""
    title: str | None = None
    chars: int = 0
    words: int = 0
    content_hash: str | None = None

    # --- structure retained, so the report can measure formatting quality ---
    headings: int = 0
    """Markdown headings in the output. Zero on a long article is a signal
    worth reporting: either the page has no sections, or its headings live in
    a different DOM branch from its prose and the extractor could not
    associate them (observed on research.google, where the headings sit in
    `div.component-intro` while the body sits in `div.blog-summary`)."""
    code_blocks: int = 0
    """Fenced code blocks retained."""

    # --- quality signals, all stored so the report can show its working ---
    link_density: float | None = None
    secondary_chars: int = 0
    """Length from readability-lxml, the cross-check extractor."""
    agreement: float | None = None
    """shorter / longer, across the two extractors. 1.0 = identical length."""

    failed_rules: list[str] = field(default_factory=list)
    """Names of the quality rules that rejected this document, in order."""

    detail: str | None = None
    """Human-readable summary of why it was rejected."""


# A line that clearly does NOT start a new paragraph: it continues the
# previous one. Lowercase letter, or punctuation that can never open a
# sentence. This is the signal used to undo trafilatura's spurious breaks.
_CONTINUATION_START_RE = re.compile(r"^[a-z,;:.!?)\]}]")

# A line that clearly does not END a sentence: it lacks terminal punctuation.
#
# The backtick is NOT in this exclusion list, and that omission is the whole
# point. The exact case being fixed is a line ending in an inline code span:
#
#     I think my favourite template filter is `querystring`
#
# A closing backtick marks the end of a code span, not the end of a sentence,
# so such a line IS unfinished. The first version of this pattern treated ` as
# terminal punctuation, which made the rule silently never fire on the very
# input it was written for -- caught by testing the predicate directly rather
# than eyeballing the output.
_UNFINISHED_END_RE = re.compile(r"[^.!?;\"')\]}’”]$")

# Structural Markdown lines that must never be joined to a neighbour.
_STRUCTURAL_LINE_RE = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```)")


def _rejoin_split_sentences(text: str) -> str:
    """Undo paragraph breaks that trafilatura inserts around inline code.

    THE BUG THIS FIXES. In markdown mode trafilatura terminates a paragraph
    after every inline `code` span, so one sentence is shredded into three:

        my favourite template filter is `querystring`
        <blank>
        : in this site sometimes we use filters like `?date=2026-06-01`
        <blank>
        to decide what is displayed.

    Verified to come from trafilatura itself, not from our post-processing,
    by inspecting its raw output before anything else touches it.

    THE RULE. A blank line is removed only when the text around it proves it
    is spurious: the line before ends mid-sentence (no closing punctuation)
    AND the line after begins with a lowercase letter or punctuation that
    cannot start a sentence. Both conditions must hold.

    Deliberately conservative. A genuine paragraph break has a capital letter
    or a bullet after it and a full stop before it, so it fails the test and
    survives. Headings, list items, quotes and code fences are excluded
    outright -- joining those would corrupt the structure this change exists
    to preserve.
    """
    if "\n\n" not in text:
        return text

    blocks = text.split("\n\n")
    merged: list[str] = [blocks[0]] if blocks else []

    for block in blocks[1:]:
        previous = merged[-1] if merged else ""
        prev_last_line = previous.rstrip().split("\n")[-1] if previous else ""
        next_first_line = block.lstrip().split("\n")[0] if block.strip() else ""

        # A block that CONTAINS a list item anywhere is off limits, not just
        # one that starts with a marker. This is the bug that turned a
        # three-bullet list into one: trafilatura had already split the items
        # into fragments, so the marker sat on the first fragment and the
        # continuation checks happily glued the rest onto it.
        prev_has_item = any(
            _STRUCTURAL_LINE_RE.match(l) for l in previous.split("\n")
        )
        next_has_item = any(
            _STRUCTURAL_LINE_RE.match(l) for l in block.split("\n")
        )

        joinable = (
            prev_last_line
            and next_first_line
            and not prev_has_item
            and not next_has_item
            and _UNFINISHED_END_RE.search(prev_last_line)
            and _CONTINUATION_START_RE.match(next_first_line)
        )

        if joinable:
            # Single space, not a newline: these were one sentence.
            merged[-1] = previous.rstrip() + " " + block.lstrip()
        else:
            merged.append(block)

    return "\n\n".join(merged)


def normalise_text(text: str) -> str:
    """Canonical whitespace form. Used for hashing, storage and length.

    Applied before hashing so that two copies of one article differing only in
    trailing whitespace produce the SAME hash -- otherwise exact-duplicate
    detection silently misses most real duplicates.

    LEADING whitespace is now PRESERVED, which is a change. The original
    stripped both ends of every line, which is correct for plain text and
    destructive for Markdown: nested bullets lose their nesting, and indented
    code blocks stop being code blocks. Since the extractor now emits
    Markdown, indentation carries meaning and cannot be normalised away.

    Only trailing whitespace is stripped -- it is invisible, never meaningful,
    and is exactly the kind of incidental difference hashing must ignore.
    """
    if not text:
        return ""
    # Unify line endings first: a Windows-served copy of a Unix-served page
    # would otherwise hash differently.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        # Inside a ``` fence, leave the line completely alone: collapsing runs
        # of spaces there would reindent code and change what it means.
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line.rstrip())
            continue
        if in_fence:
            out.append(line.rstrip())
            continue
        # Outside code, collapse runs of spaces/tabs WITHIN the line but keep
        # the indent that starts it, so list nesting survives.
        indent = line[: len(line) - len(stripped)]
        out.append((indent + _WHITESPACE_RE.sub(" ", stripped)).rstrip())

    text = "\n".join(out)
    text = _rejoin_split_sentences(text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


def strip_boilerplate_lines(text: str) -> tuple[str, int]:
    """Drop whole lines that are share widgets, cookie notices and the like.

    Runs AFTER trafilatura, which already removes most chrome. This catches
    the residue that survives because it sits inside the article container.

    Returns the cleaned text and how many lines were removed, so the report
    can state how much residual boilerplate the primary extractor left.
    """
    kept: list[str] = []
    removed = 0
    in_fence = False
    for line in text.split("\n"):
        # Never strip inside a code block. "advertisement" or "loading..."
        # can be a legitimate identifier or output line in someone's code
        # sample, and silently deleting a line from a code block corrupts it
        # in a way a reader cannot detect.
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            kept.append(line)
            continue
        if not in_fence and any(
            pattern.match(line) for pattern in _BOILERPLATE_LINE_PATTERNS
        ):
            removed += 1
            continue
        kept.append(line)
    return _BLANKLINES_RE.sub("\n\n", "\n".join(kept)).strip(), removed


# Headings that mark the start of a "more posts" list at the end of an
# article. Everything from such a heading to the end is chrome, not content.
_LINK_LIST_HEADING_RE = re.compile(
    # Same Markdown-prefix allowance as the boilerplate patterns: since the
    # extractor emits Markdown, this heading now usually arrives as
    # "### Recent articles" rather than bare text.
    _MD_PREFIX
    + r"(recent|latest|popular|related|previous|other|more)\s+"
    r"(articles?|posts?|stories|reading)\s*:?\s*$",
    re.I,
)

# A line that looks like an entry in such a list: a bullet ending in a date.
# Both halves are required, which is what stops it eating ordinary bulleted
# prose in the middle of an article.
_LINK_LIST_ITEM_RE = re.compile(
    r"^\s*[-*•]\s+.+?\s+-\s+\d{1,2}(st|nd|rd|th)?\s+\w+\s+\d{4}\s*$",
    re.I,
)


def strip_trailing_link_list(text: str) -> tuple[str, int]:
    """Remove a "Recent articles" style list from the END of an article.

    WHY THIS EXISTS. Found by reading what the crawler actually rejected on
    the first live run: three genuine Simon Willison articles were binned as
    junk with link densities of 0.38-0.43, just over the 0.35 threshold. The
    article bodies were clean; what pushed them over was a "Recent articles"
    list of other posts that survived extraction.

    The tempting fix was to raise the threshold until they passed. That would
    have been wrong twice over: it weakens the rule against genuine
    navigation pages, and it leaves the junk links inside the stored text --
    the brief asks for the article, not the article plus a sitemap.

    So this removes the cause instead, and the density is then re-measured on
    what remains. A page that is STILL link-heavy afterwards is genuinely
    navigation and is still rejected.

    Only trailing lists are cut: the scan starts at the end and stops at the
    first line that is neither a list item nor blank. A "related posts" block
    in the MIDDLE of an article would be left alone, because cutting there
    would truncate real content.
    """
    lines = text.split("\n")
    cut_at = len(lines)
    index = len(lines) - 1

    while index >= 0:
        line = lines[index]
        if not line.strip():
            index -= 1
            continue
        if _LINK_LIST_ITEM_RE.match(line):
            cut_at = index
            index -= 1
            continue
        if _LINK_LIST_HEADING_RE.match(line) and cut_at <= index + 1:
            # The heading immediately above the items -- cut from here.
            cut_at = index
        break

    if cut_at >= len(lines):
        return text, 0

    removed = len(lines) - cut_at
    return "\n".join(lines[:cut_at]).strip(), removed


# Markdown link syntax: [visible text](https://url) -> visible text.
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _strip_md_link_syntax(text: str) -> str:
    """Reduce [text](url) to just text.

    Used only for measurement, never for storage. Length and link-density are
    questions about the PROSE a reader sees; the URLs behind the links are
    metadata and counting their characters would distort both.
    """
    return _MD_LINK_RE.sub(r"\1", text)


def compute_link_density(html: str, keep_text: str | None = None) -> float | None:
    """Fraction of visible characters that sit inside <a> tags.

    Navigation, tag clouds and "related posts" blocks are almost entirely
    links; prose is not. This is the signal that catches a "successful"
    extraction which actually grabbed the sidebar.

    Measured on the SOURCE HTML rather than the extracted text, because by the
    time trafilatura has finished the links are gone -- measuring its output
    would always report ~0 and detect nothing.

    `keep_text` narrows the measurement to the part of the document we
    actually kept. Without it, the density reflects the whole page including
    the nav and footer that extraction already removed, so a clean article on
    a link-heavy site scores as junk for chrome that is not in the output.
    Anchors are counted only when their text appears in what we kept.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - malformed HTML is the norm, not a bug
        return None

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    if keep_text:
        # Normalise both sides so whitespace differences between the DOM and
        # the extracted text do not cause false misses.
        haystack = " ".join(keep_text.split())
        total = len(haystack.replace(" ", ""))
        if total == 0:
            return None
        linked = 0
        for anchor in soup.find_all("a"):
            anchor_text = " ".join(anchor.get_text(strip=True).split())
            # Anchors under 3 chars ("1", ">") are pagination furniture and
            # match by accident all over the place.
            if len(anchor_text) >= 3 and anchor_text in haystack:
                linked += len(anchor_text.replace(" ", ""))
        return round(min(1.0, linked / total), 4)

    total = len(soup.get_text(strip=True))
    if total == 0:
        return None

    linked = sum(len(a.get_text(strip=True)) for a in soup.find_all("a"))
    return round(linked / total, 4)


# Inline tags that must be unwrapped from inside a heading. Each was verified
# to cause trafilatura to drop the heading or its text -- see the docstring.
_HEADING_INLINE_TAGS = ("a", "code", "span", "em", "strong", "b", "i", "tt", "kbd", "samp")


def unwrap_heading_anchors(html: str) -> str:
    """Flatten inline tags inside headings to their bare text.

    TWO SEPARATE FAILURES, both found on one Julia Evans post and both
    reproduced in isolation before fixing:

    1. SELF-LINKING HEADINGS. Static-site generators render headings as
       self-links so the section is clickable:

           <h3 id="why-learn"><a href="#why-learn">why learn ...</a></h3>

       With include_links=False trafilatura drops the anchor text and emits
       a heading with no content -- literally "###".

       Turning include_links ON is WORSE, not better: measured on the same
       page it empties NINE of the ten headings instead of one, because each
       becomes a Markdown link whose text is then lost.

    2. INLINE <code> IN A HEADING. This one drops the WHOLE heading, not just
       the code:

           <h3><code>querystring</code> is cool</h3>   ->  (nothing at all)

       Confirmed with a minimal fixture: a plain <h3> survives, an <h3>
       containing <code> vanishes entirely, and an <h3> that is only <code>
       vanishes too. That is why "querystring is cool" was missing from the
       stored article rather than merely unformatted.

    Neither is fixable through trafilatura's options, so the tags are removed
    before it sees the document. Unwrapping preserves the text and discards
    only presentational markup, which a plain-text article does not need.

    ONLY HEADINGS ARE TOUCHED. Links, code and emphasis in body prose are
    left exactly as they are, so this cannot change how the article body is
    extracted -- it only rescues headings that would otherwise disappear.
    """
    if not html or "<h" not in html.lower():
        return html
    try:
        soup = BeautifulSoup(html, "lxml")
        changed = False
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            for tag in heading.find_all(_HEADING_INLINE_TAGS):
                # unwrap() replaces the tag with its children, so the text
                # survives and the wrapper disappears.
                tag.unwrap()
                changed = True
        return str(soup) if changed else html
    except Exception:  # noqa: BLE001 - malformed HTML must not kill the run
        return html


def restore_code_indentation(text: str, html: str) -> tuple[str, int]:
    """Put the original indentation back inside fenced code blocks.

    THE BUG. trafilatura strips leading whitespace from every line of a code
    block. Verified by comparing the source HTML with its output on a real
    page -- the source has

        class EventQuerySet(...):
            def approved(self):
                return self.filter(...)

    and trafilatura emits all three lines flush left. For Python that is not
    a cosmetic loss: the stored snippet is syntactically invalid and would
    not run if a reader copied it.

    THE FIX. The raw HTML is already in hand, and <pre> preserves whitespace
    by definition, so the correct text is available -- take it from the DOM
    instead of trusting the converter.

    MATCHING IS BY FIRST NON-BLANK LINE, deliberately. Matching on the whole
    block cannot work: the flattened and original forms differ by exactly the
    whitespace being restored, so they never compare equal. The first line of
    a code block is almost always distinctive within one article, and a
    length sanity-check guards the rare collision -- a candidate whose line
    count differs wildly from the block it would replace is rejected rather
    than substituted.

    Blocks that cannot be matched are LEFT ALONE. A wrong replacement is far
    worse than a missing indent, so the failure mode is "no change".
    """
    if "```" not in text or "<pre" not in html.lower():
        return text, 0

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return text, 0

    # Map first-line -> full original text, for every <pre> on the page.
    originals: dict[str, list[str]] = {}
    for pre in soup.find_all("pre"):
        # get_text() on <pre> keeps newlines and leading spaces intact.
        original = pre.get_text()
        if not original.strip():
            continue
        first = next((l.strip() for l in original.splitlines() if l.strip()), "")
        if first:
            originals.setdefault(first, []).append(original.strip("\n"))

    if not originals:
        return text, 0

    out: list[str] = []
    restored = 0
    lines = text.split("\n")
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("```"):
            out.append(line)
            index += 1
            continue

        # Collect the fenced block.
        fence_open = line
        body: list[str] = []
        index += 1
        while index < len(lines) and not lines[index].lstrip().startswith("```"):
            body.append(lines[index])
            index += 1
        fence_close = lines[index] if index < len(lines) else "```"
        index += 1

        first = next((l.strip() for l in body if l.strip()), "")
        candidates = originals.get(first)
        replacement = None
        if candidates:
            for candidate in candidates:
                # Sanity check: the original may legitimately have MORE lines
                # (trafilatura drops blank lines between methods), but a wild
                # mismatch means we matched the wrong block.
                if len(candidate.splitlines()) >= len(body) and (
                    len(candidate.splitlines()) <= len(body) * 3 + 4
                ):
                    replacement = candidate
                    break

        if replacement is not None and replacement.splitlines() != body:
            out.append(fence_open)
            out.extend(replacement.splitlines())
            out.append(fence_close)
            restored += 1
        else:
            out.append(fence_open)
            out.extend(body)
            out.append(fence_close)

    return "\n".join(out), restored


def _inline_markdown(node) -> str:
    """Render a DOM node's children to inline Markdown.

    Handles the four inline constructs that carry meaning in an article:
    code, links, bold, italic. Everything else contributes its text.
    Deliberately small -- this renders the inside of ONE list item, not a
    general HTML-to-Markdown converter.
    """
    from bs4 import NavigableString, Tag

    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            inner = _inline_markdown(child)
            name = child.name.lower()
            if name == "code":
                # Only fence it if it is not already inside a code span.
                parts.append(f"`{inner.strip()}`" if inner.strip() else "")
            elif name == "a":
                href = (child.get("href") or "").strip()
                parts.append(f"[{inner.strip()}]({href})" if href and inner.strip() else inner)
            elif name in ("strong", "b"):
                parts.append(f"**{inner.strip()}**" if inner.strip() else "")
            elif name in ("em", "i"):
                parts.append(f"*{inner.strip()}*" if inner.strip() else "")
            elif name == "br":
                parts.append(" ")
            else:
                parts.append(inner)
    # Collapse the whitespace the source HTML used for indentation.
    return " ".join("".join(parts).split())


def _match_key(value: str) -> str:
    """Reduce text to a form that compares equal across converters.

    Both sides of a list match are the "same" text rendered by different
    code: BeautifulSoup's get_text(' ') and trafilatura's Markdown. They
    disagree on spacing around punctuation and on the backticks, asterisks
    and brackets the converter inserts.

    Two real mismatches this exists to absorb, both found by debugging a list
    that silently refused to rebuild:
      - `<code>json_script</code>, which...` -> "json_script , which" from
        get_text(' ') but "`json_script`, which" from trafilatura
      - "the HTML as a <script> tag" -> "a`<script>` tag", with backticks
        inserted mid-phrase

    Dropping all non-alphanumerics makes both sides comparable without
    guessing which converter did what.
    """
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def restore_list_items(text: str, html: str) -> tuple[str, int]:
    """Rebuild bullet lists that trafilatura split apart.

    THE BUG, reported by a reviewer who counted the bullets: a three-item list
    in the source arrived as ONE bullet with all three items run together.

    Cause, confirmed by reading trafilatura's raw output: it terminates a list
    item at every inline `code` span, so

        <li>formatting dates ({{ row.date|date:"M j" }})</li>

    comes out as several fragments with only the FIRST carrying a "-" marker.
    Our sentence-rejoiner then compounded it by gluing the fragments into one
    line -- by that point the markers were already gone, so it could not tell
    an item boundary from a mid-sentence break.

    This is CONTENT loss, not formatting loss: a reader counting three
    recommendations finds one.

    THE FIX is the one that already worked for code indentation -- the DOM has
    the real structure, so read the list from there instead of trying to
    repair the converter's output.

    Each <ul>/<ol> is located in the extracted text by its FIRST item's
    opening words, and the run of text covering that list is replaced with a
    properly rendered one. Lists whose first item cannot be located are left
    untouched.
    """
    if not text or not re.search(r"<[uo]l[ >]", html, re.I):
        return text, 0

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return text, 0

    fixed = 0
    for list_tag in soup.find_all(["ul", "ol"]):
        # Skip navigation-ish lists: those are chrome the extractor already
        # (correctly) dropped, and "restoring" them would put nav back in.
        items = [li for li in list_tag.find_all("li", recursive=False)]
        if len(items) < 2:
            continue

        ordered = list_tag.name.lower() == "ol"
        rendered = []
        for number, item in enumerate(items, start=1):
            body = _inline_markdown(item)
            if not body:
                continue
            marker = f"{number}." if ordered else "-"
            rendered.append(f"{marker} {body}")
        if len(rendered) < 2:
            continue

        # Anchor on the first item's opening words, compared on the
        # punctuation-insensitive key so converter differences do not defeat
        # the match.
        first_key = _match_key(items[0].get_text(" ", strip=True))[:30]
        last_key = _match_key(items[-1].get_text(" ", strip=True))
        # A short key is only a problem if it is AMBIGUOUS. The original
        # guard required 12+ characters, which silently skipped a genuine
        # three-step ordered list whose first item keyed to "firstdothis"
        # (11). Requiring uniqueness instead of length is the property that
        # actually matters -- a short key appearing exactly once in the
        # document identifies its list just as well as a long one.
        if len(first_key) < 6 or len(last_key) < 6:
            continue

        blocks = text.split("\n\n")
        keys = [_match_key(block) for block in blocks]

        matches = [i for i, k in enumerate(keys) if first_key in k]
        if len(matches) != 1:
            # Zero matches: the list is not in the extracted text (usually a
            # nav menu the extractor correctly dropped).
            # Several matches: the key is ambiguous, so we cannot tell which
            # occurrence is the list. Guessing risks replacing the wrong span.
            continue
        start = matches[0]

        # NOTE: no "already looks fine, skip it" shortcut.
        #
        # An earlier version only rebuilt lists that were visibly split. That
        # covered the reported bug but measured at just 25% of real body list
        # items rendered with markers, because trafilatura also drops markers
        # in ways that are not obviously "split" -- and it renders <ol> as
        # "-" bullets, losing the numbering entirely.
        #
        # Rebuilding unconditionally from the DOM is simpler and strictly
        # more accurate: the DOM is the source of truth for what the author
        # wrote. The safety comes from the match being unique and the span
        # being size-checked below, not from guessing whether a repair is
        # needed.

        # The last item's text may be spread over several blocks -- that
        # splitting is exactly what this function undoes. So walk forward
        # while the accumulated text is still consuming the final item, and
        # stop at the first block that contributes nothing to it.
        end = start
        consumed = ""
        for index in range(start, min(start + 12, len(blocks))):
            consumed += keys[index]
            end = index
            if last_key[-20:] and last_key[-20:] in consumed:
                break
        else:
            # Never saw the end of the final item; replacing a guessed span
            # risks swallowing real prose, so leave this list alone.
            continue

        # Refuse to replace a span that is much larger than the list itself.
        # If the arithmetic is off, this is what stops the function deleting
        # paragraphs of an article.
        replacement = "\n".join(rendered)
        original_len = len("\n\n".join(blocks[start : end + 1]))
        if original_len > len(replacement) * 3 + 400:
            continue

        blocks[start : end + 1] = [replacement]
        text = "\n\n".join(blocks)
        fixed += 1

    return text, fixed


def restore_blockquotes(text: str, html: str) -> tuple[str, int]:
    """Re-mark quoted passages with Markdown '>' prefixes.

    WHY THIS MATTERS MORE THAN IT LOOKS. trafilatura keeps blockquote TEXT but
    drops the marker, so a passage the author was quoting from someone else
    becomes indistinguishable from their own words. Measured across six real
    cached pages: text present in all six, '>' marker in none.

    That is not a formatting nicety -- it changes attribution. On a Simon
    Willison link-blog post the quoted passage IS the substance of the piece,
    and reading it as his own writing misrepresents both parties.

    Matched by the first sentence of each blockquote, then every line of the
    matching paragraph is prefixed. Unmatched quotes are left alone: a
    mis-marked quote would be worse than an unmarked one.
    """
    if not text or "<blockquote" not in html.lower():
        return text, 0

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return text, 0

    # Opening fragments of each blockquote, longest first so the most
    # specific match wins when one quote starts with another's words.
    openers: list[str] = []
    for quote in soup.find_all("blockquote"):
        quoted = " ".join(quote.get_text(" ", strip=True).split())
        if len(quoted) >= 40:
            openers.append(quoted)
    if not openers:
        return text, 0
    openers.sort(key=len, reverse=True)

    blocks = text.split("\n\n")
    marked = 0
    for position, block in enumerate(blocks):
        flat = " ".join(block.split())
        if not flat or block.lstrip().startswith((">", "#", "```")):
            continue
        for quoted in openers:
            # A 60-character prefix is long enough to be unambiguous and
            # short enough to survive trafilatura's whitespace changes.
            probe = quoted[:60]
            if probe and probe in flat:
                blocks[position] = "\n".join(
                    f"> {line}" if line.strip() else ">"
                    for line in block.split("\n")
                )
                marked += 1
                break

    return "\n\n".join(blocks), marked


def _extract_primary(html: str, url: str | None) -> tuple[str, str | None]:
    """trafilatura: the extractor whose output we keep."""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            # Markdown, not plain text. The default 'txt' format flattens the
            # document: headings become ordinary lines indistinguishable from
            # prose, and code blocks lose their fences entirely. Reported by
            # the user on a Julia Evans post -- the paragraphs were all there
            # but its 9 section headings and 4 code blocks had vanished, so
            # the stored article read as one undifferentiated wall of text.
            #
            # Markdown keeps the structure the author wrote (## headings,
            # ``` fences, - bullets) while still being plain text that any
            # consumer can read. Measured on that page: 8941 chars with 0
            # headings and 0 fences -> 9482 chars with 10 headings and 8
            # fences.
            output_format="markdown",
            # These flags are the difference between an article and an
            # article plus its comment section and navigation.
            include_comments=False,
            include_tables=True,     # data tables are often the point
            include_images=False,
            # Keep bold and italic. Emphasis is authorial intent, not
            # decoration -- "do NOT do this" reads differently unemphasised.
            include_formatting=True,
            # Keep links as Markdown [text](url).
            #
            # This was OFF, and turning it on used to empty nine of ten
            # headings, because trafilatura converted each heading's own
            # self-anchor into a link and lost the text. That is no longer
            # true: unwrap_heading_anchors() now removes those anchors before
            # extraction, so links can be kept in body prose without touching
            # headings. Re-measured on the reported page after the unwrap
            # landed: 8 links restored, 10 headings intact, 0 empty.
            #
            # Worth keeping because a link is information. "See this post"
            # with the URL stripped is strictly less useful than the original,
            # and the brief asks for the article as published.
            include_links=True,
            #
            # favor_precision is deliberately NOT set, and that is a reversal.
            # It was on originally, on the reasoning that dropping a paragraph
            # beats keeping navigation. Measuring showed what it actually
            # dropped: EVERY heading. On the Julia Evans post it took the
            # count from 10 to 0; on a Cloudflare post from 7 to 6.
            #
            # Checked for the boilerplate it was supposed to be protecting
            # against -- across three sites (jvns.ca, blog.cloudflare.com,
            # research.google) turning it off introduced no nav, no footer,
            # no share buttons, no cookie notice. It was paying a certain
            # cost for a benefit that did not materialise on this corpus.
            #
            # The junk rules (length, link density, extractor cross-check)
            # remain the real defence against bad extractions, and they are
            # measured rather than assumed.
        ) or ""
    except Exception:  # noqa: BLE001 - never let one bad page kill the run
        text = ""

    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta is not None:
            title = (meta.title or "").strip() or None
    except Exception:  # noqa: BLE001
        title = None

    return text, title


def _extract_secondary(html: str) -> str:
    """readability-lxml: used ONLY for its length, as an independent check."""
    try:
        summary_html = ReadabilityDocument(html).summary()
        return BeautifulSoup(summary_html, "lxml").get_text(separator="\n")
    except Exception:  # noqa: BLE001
        return ""


def extract(html: str, url: str | None, config: Config) -> ExtractionResult:
    """Extract and quality-score one page.

    Returns ok=False with `failed_rules` populated when the result should not
    be stored. The caller maps that to EXTRACTION_FAILED or JUNK.
    """
    if not html or not html.strip():
        return ExtractionResult(
            ok=False, failed_rules=["empty_html"], detail="No HTML to extract from."
        )

    # Unwrap self-linking headings before extraction, or they arrive empty.
    # Applied to the copy fed to BOTH extractors so the cross-check compares
    # like with like.
    html = unwrap_heading_anchors(html)

    raw_text, title = _extract_primary(html, url)

    # Rebuild split-apart lists BEFORE normalise_text.
    #
    # Order matters and was found by getting it wrong: normalise_text runs the
    # sentence-rejoiner, which merges paragraph fragments. Given a list whose
    # items trafilatura has already shredded, the rejoiner cannot tell an item
    # boundary from a mid-sentence break and welds three bullets into one.
    # Restoring the list first means the rejoiner sees proper list markers and
    # leaves them alone.
    text, lists_fixed = restore_list_items(raw_text, html)

    text = normalise_text(text)

    # Restore what the markdown converter dropped, using the DOM as the
    # source of truth. These run AFTER normalise_text: it is what collapses
    # whitespace, so restoring first would have its work undone.
    #
    # Code indentation first -- normalise_text leaves fenced blocks alone, so
    # the fences it produced are already stable landmarks to match against.
    text, code_restored = restore_code_indentation(text, html)
    text, quotes_marked = restore_blockquotes(text, html)

    text, boilerplate_removed = strip_boilerplate_lines(text)
    # Remove a trailing "Recent articles" list BEFORE measuring density, so
    # the measurement describes the text we are actually keeping. Measuring
    # first would judge the article on chrome we are about to discard.
    text, link_list_lines_removed = strip_trailing_link_list(text)

    secondary = normalise_text(_extract_secondary(html))
    # Scoped to the kept text -- see compute_link_density for why.
    #
    # Measured against the text with Markdown link SYNTAX removed. Now that
    # links are kept as [text](url), the raw string contains every URL, and
    # counting those characters would inflate link density on exactly the
    # articles that cite their sources well -- pushing good writing over the
    # junk threshold. The density question is "how much of this is link
    # TEXT", which is what the visible label measures.
    link_density = compute_link_density(html, keep_text=_strip_md_link_syntax(text))

    # Length is measured on the VISIBLE prose, with Markdown link syntax
    # reduced to its label. Otherwise every stored URL inflates the count,
    # the minimum-length gate gets easier to pass on link-heavy pages, and
    # the report's mean/median article length silently drifts upward for a
    # reason that has nothing to do with how much was written.
    measurable = _strip_md_link_syntax(text)
    chars = len(measurable)
    words = len(measurable.split()) if measurable else 0
    secondary_chars = len(secondary)

    # Agreement = shorter / longer. Symmetric, so it does not matter which
    # extractor happened to win.
    agreement = None
    longer = max(chars, secondary_chars)
    if longer > 0:
        agreement = round(min(chars, secondary_chars) / longer, 4)

    result = ExtractionResult(
        ok=True,
        text=text,
        title=title,
        chars=chars,
        words=words,
        headings=sum(1 for line in text.splitlines() if line.lstrip().startswith("#")),
        # Fences come in pairs, so halve the count to get blocks.
        code_blocks=text.count("```") // 2,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        link_density=link_density,
        secondary_chars=secondary_chars,
        agreement=agreement,
    )

    # ---------------- quality rules ----------------
    # Each appends a NAMED rule so the report can group rejections by cause.
    failures: list[str] = []
    details: list[str] = []

    # Rule 1: nothing came out at all. This is EXTRACTION_FAILED territory,
    # distinct from "came out but is bad".
    if chars == 0:
        result.ok = False
        result.failed_rules = ["no_text_extracted"]
        result.detail = "Neither extractor found article text on the page."
        return result

    # Rule 2: too short to be an article. The task predicts these are garbage
    # ("your 5 shortest -- open those"), and this is where they get caught.
    if chars < config.min_article_chars:
        failures.append("too_short")
        details.append(f"only {chars} chars (minimum {config.min_article_chars})")

    # Rule 3: mostly links -> this is navigation, not prose.
    if link_density is not None and link_density > config.max_link_density:
        failures.append("high_link_density")
        details.append(
            f"link density {link_density:.2f} exceeds {config.max_link_density}"
        )

    # Rule 4: the two extractors disagree sharply AND the primary returned
    # less than the secondary -- meaning trafilatura probably missed the
    # article body.
    #
    # THE DIRECTION OF THE COMPARISON IS THE WHOLE RULE, and getting it wrong
    # was a real bug. The first version fired on any large disagreement, which
    # rejected all five Google Research articles: trafilatura returned
    # 6,500-11,000 characters of correctly-extracted prose while readability
    # found only ~2,000. Reading the stored text confirmed the primary output
    # was clean and complete. The rule was blaming the wrong extractor.
    #
    # Only the case where the PRIMARY is much shorter is evidence against the
    # output we actually keep: it means trafilatura latched onto a summary or
    # a sidebar while readability found the real body. When the primary is
    # LONGER, the most likely explanation is that readability -- the cruder
    # algorithm -- gave up early, which says nothing about our result.
    #
    # This is also why `agreement` is still stored unconditionally: the report
    # shows the cross-check for every document, whichever way it fell.
    if (
        agreement is not None
        and agreement < config.extractor_agreement_ratio
        and chars < secondary_chars          # the primary is the short one
        and secondary_chars > config.min_article_chars
    ):
        failures.append("extractor_disagreement")
        details.append(
            f"primary extractor returned much less than the cross-check "
            f"({chars} vs {secondary_chars} chars, agreement {agreement:.2f} "
            f"< {config.extractor_agreement_ratio}), so it likely missed the body"
        )

    if failures:
        result.ok = False
        result.failed_rules = failures
        result.detail = "; ".join(details)

    notes = []
    if boilerplate_removed:
        notes.append(f"removed {boilerplate_removed} boilerplate line(s)")
    if link_list_lines_removed:
        notes.append(f"removed a trailing link list ({link_list_lines_removed} lines)")
    if lists_fixed:
        notes.append(f"rebuilt {lists_fixed} split list(s)")
    if code_restored:
        notes.append(f"restored indentation in {code_restored} code block(s)")
    if quotes_marked:
        notes.append(f"re-marked {quotes_marked} blockquote(s)")
    if notes:
        joined = "; ".join(notes)
        result.detail = f"{result.detail}; {joined}" if result.detail else joined

    return result
