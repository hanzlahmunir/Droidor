"""Article extraction and quality scoring.

TWO JOBS, TWO TOOLS -- and separating them is the central design decision.

    FINDING the article   -> trafilatura
    RENDERING it          -> markdownify, over the ORIGINAL DOM

WHY THEY ARE SPLIT. The first version used trafilatura for both, and its
Markdown converter is lossy in ways that cost real content. Measured on one
reported page: 0 list markers where the source had 41, code blocks with their
indentation stripped, and -- worst -- text REORDERED. `Run <code>/cost</code>.
Find out where...` came out as `**Run**Find out where...\\`/cost\\`.`, with the
code span moved to the end of the sentence.

Five repair functions were written to patch that damage and were then deleted,
because the approach has a ceiling: a repair has to LOCATE the damaged text,
but the damage reorders it, so the matcher cannot find what it is meant to
fix. Each new site with a different nesting pattern broke it again. That is
the opposite of an automated system.

Rendering from the DOM is correct BY CONSTRUCTION instead. <ul> is a list,
<li> is an item, <pre> preserves whitespace, <strong> is bold, and nesting
order is reading order. There is no damage to repair.

WHY TRAFILATURA IS STILL HERE. Finding which element holds the article is the
genuinely hard part, and it is what trafilatura is best in class at (mean F1
0.883 across eight datasets). A naive `find('article') or find('main')` failed
on 3 of 10 real pages in this corpus. So trafilatura still decides WHAT the
article is; it just no longer decides how it is written down.

readability-lxml runs third, as a CROSS-CHECK only. Its output is discarded;
its LENGTH is kept. The task asks for "% of pages where extraction failed or
returned junk" -- a real number. With one extractor there is nothing to
compare against, so junk could only be asserted. Two independent algorithms
disagreeing sharply is evidence.

THE QUALITY RULES ARE EXPLICIT AND NAMED. Each rejection records which rule
fired, so "% junk" decomposes by cause instead of being one opaque figure.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
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
    list_items: int = 0
    """Bullet and numbered list items retained. Tracked because a reviewer
    counting three bullets in the source and finding one in the output is how
    the biggest extraction bug in this project was found."""

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
# Tags removed from the article subtree before rendering. These are chrome
# that can legitimately sit INSIDE the container trafilatura picks, and none
# of them is ever article prose.
_CHROME_TAGS = (
    "script", "style", "noscript", "nav", "footer", "aside",
    "form", "iframe", "svg", "button", "template",
)

# How much of trafilatura's text the candidate element must contain before it
# is considered a match. Below 1.0 because the two disagree slightly at the
# edges -- trafilatura trims a trailing byline the DOM node still holds.
_FINGERPRINT_COVERAGE = 0.80

# Reject a candidate carrying far more text than trafilatura kept: that means
# we climbed too far up the tree and grabbed the page, not the article.
# Measured across the corpus: median ratio 1.00, worst 1.46, so 2.0 is a
# generous ceiling that still catches a genuine mis-selection.
_FINGERPRINT_MAX_RATIO = 2.0


class _ArticleConverter(MarkdownConverter):
    """markdownify with the conventions this project stores in.

    Subclassed rather than configured because two behaviours needed
    overriding outright, both found by comparing output against real pages.
    """

    # Signatures match markdownify 0.14's convert_<tag>(self, el, text,
    # convert_as_inline). Pinned in requirements.txt for exactly this reason:
    # the first attempt used a newer release's `parent_tags` keyword and every
    # page raised TypeError -- caught immediately because the article rendered
    # with zero headings and zero links.

    def convert_a(self, el, text, convert_as_inline):
        """Drop heading self-anchors; keep real links.

        Static-site generators wrap headings in a link to their own id
        (`<h3 id="x"><a href="#x">text</a></h3>`). Rendering that as a link
        gives `### [text](#x)`, which is noise -- the anchor points at the
        heading the reader is already looking at.
        """
        href = (el.get("href") or "").strip()
        if href.startswith("#"):
            return text
        return super().convert_a(el, text, convert_as_inline)

    def convert_img(self, el, text, convert_as_inline):
        """Images are dropped: this pipeline stores article TEXT.

        Alt text is kept where present, since an alt attribute is often a
        real sentence (a chart caption, a diagram description).
        """
        alt = (el.get("alt") or "").strip()
        return f"{alt} " if alt else ""


def _match_key(value: str) -> str:
    """Reduce text to a comparison key: lowercase alphanumerics only.

    Used to compare trafilatura's plain-text output against DOM text. The two
    disagree constantly on whitespace and punctuation spacing, and neither
    difference is meaningful for deciding "is this the same content".
    """
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def find_article_node(html: str, plain_text: str):
    """Locate the ORIGINAL DOM element holding the article trafilatura found.

    THE PROBLEM THIS SOLVES. trafilatura decides what the article is, and it
    is very good at that. But it will only hand back its own text or its own
    simplified HTML -- and both are already lossy. Its HTML output normalises
    <ol> to <ul> and strips <code> entirely, so even converting THAT loses a
    numbered checklist. Only the original DOM has everything.

    So: use trafilatura's extracted text as a FINGERPRINT, and find the
    smallest original element that contains it.

    Smallest matters. Every ancestor of the article also contains the article,
    all the way up to <html>. Taking the smallest gives the tightest container
    -- the article and as little else as possible.

    WHY NOT `find('article') or find('main')`. Tried first, and it failed on
    3 of 10 real pages in this corpus, which have neither element. The
    fingerprint approach located the right node on 29 of 29 cached pages,
    median coverage ratio 1.00.

    Returns None when nothing matches, and the caller falls back.
    """
    if not plain_text or not plain_text.strip():
        return None

    target = _match_key(plain_text)
    if len(target) < 100:
        # Too little text to fingerprint reliably; a short key would match
        # half the page.
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return None

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    minimum = len(target) * _FINGERPRINT_COVERAGE
    ceiling = len(target) * _FINGERPRINT_MAX_RATIO

    best = None
    best_size = None
    # Only container-shaped elements are candidates. Checking every tag was
    # measurably slower with no benefit -- an article never lives in a <span>.
    for element in soup.find_all(["article", "main", "div", "section", "body"]):
        size = len(_match_key(element.get_text(" ")))
        if size < minimum or size > ceiling:
            continue

        # Reject candidates that are mostly links.
        #
        # Found as a regression when this replaced the old extractor: on a
        # Cloudflare article the smallest qualifying element was a
        # `dropdown-container` -- a site-wide nav menu that links to enough
        # pages to contain the article's vocabulary. It rendered as 764
        # bullets at link density 0.96.
        #
        # "Smallest container holding the text" is necessary but not
        # sufficient; the container also has to look like prose. The junk
        # gate did catch this one downstream, but relying on that would mean
        # losing an article we can extract correctly.
        text_length = len(element.get_text(" ", strip=True))
        if text_length:
            linked = sum(
                len(a.get_text(" ", strip=True)) for a in element.find_all("a")
            )
            if linked / text_length > 0.5:
                continue

        if best_size is None or size < best_size:
            best, best_size = element, size

    return best


def render_markdown(node, base_url: str | None = None) -> str:
    """Render a DOM subtree to Markdown.

    Correct by construction: <ul> is a list, <li> is an item, <pre> preserves
    whitespace, <strong> is bold, and nesting order is reading order. There is
    no lossy conversion to repair afterwards -- which is the entire reason
    this replaced trafilatura's own converter.
    """
    # Work on a copy so the caller's soup is not mutated -- compute_link_density
    # parses the same HTML afterwards and must see it intact.
    clone = BeautifulSoup(str(node), "lxml")
    for tag in clone(_CHROME_TAGS):
        tag.decompose()

    # Make links absolute. A stored article is read away from the site it came
    # from, so "/blog/which-model" resolves against whatever host the reader
    # happens to be on -- which is either a 404 or, worse, the wrong page.
    # Seen on a real article whose entire "Further Reading" list was
    # site-relative.
    if base_url:
        for anchor in clone.find_all("a", href=True):
            href = anchor["href"].strip()
            if href and not href.startswith(("http://", "https://", "#", "mailto:")):
                anchor["href"] = urljoin(base_url, href)

    converter = _ArticleConverter(
        heading_style="ATX",        # "## Heading", not underlines
        bullets="-",                # one marker everywhere, not -/*/+ by depth
        strong_em_symbol="*",
        escape_asterisks=False,     # do not backslash-escape prose punctuation
        escape_underscores=False,
        escape_misc=False,
        code_language="",           # ``` with no language guess
    )
    return converter.convert_soup(clone)


def _extract_primary(html: str, url: str | None) -> tuple[str, str | None]:
    """Locate the article with trafilatura, render it from the original DOM."""
    # 1. trafilatura decides WHAT the article is. Plain text, because we only
    #    need it as a fingerprint -- its formatting is exactly what we are
    #    replacing.
    try:
        plain = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            include_images=False,
        ) or ""
    except Exception:  # noqa: BLE001 - never let one bad page kill the run
        plain = ""

    # 2. Find that article in the ORIGINAL DOM and render it faithfully.
    text = ""
    if plain:
        node = find_article_node(html, plain)
        if node is not None:
            try:
                text = render_markdown(node, base_url=url)
            except Exception as exc:  # noqa: BLE001
                # LOUD, not silent. The first version swallowed this, and a
                # markdownify API mismatch (a renamed keyword argument) then
                # made EVERY page fall back to unstructured text while the
                # crawl still reported success. The only visible symptom was
                # headings and links dropping to zero. A renderer failure is
                # a bug in this file, not a property of the page.
                print(f"  warning: markdown rendering failed ({exc}); "
                      "falling back to plain text")
                text = ""

    if not text.strip():
        # Fallback: trafilatura's own text. Loses structure, but a
        # structure-less article beats no article, and the quality gates
        # still judge it on its merits.
        text = plain

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

    # Render the article from the original DOM. No repair pass follows: the
    # five functions that used to patch the converter's damage (list rebuild,
    # code re-indentation, blockquote re-marking, heading-anchor unwrapping,
    # sentence rejoining) were deleted along with the damage itself.
    raw_text, title = _extract_primary(html, url)

    text = normalise_text(raw_text)

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
        list_items=sum(
            1 for line in text.splitlines()
            if re.match(r"^\s*[-*+] |^\s*\d+[.)]\s", line)
        ),
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
    if notes:
        joined = "; ".join(notes)
        result.detail = f"{result.detail}; {joined}" if result.detail else joined

    return result
