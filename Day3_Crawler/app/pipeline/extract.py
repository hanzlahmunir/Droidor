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
_BOILERPLATE_LINE_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"^\s*share (this|on)\b",
        r"^\s*(tweet|share|pin it|email this)\s*$",
        r"^\s*subscribe to (our|the) newsletter",
        r"^\s*sign up for (our|the) newsletter",
        r"^\s*(read|related|you might also like|more from|recommended)[\s:]*$",
        # Headings that introduce a trailing list of other posts. Matched as a
        # whole line so an article whose prose mentions "recent articles" is
        # untouched. See _strip_trailing_link_list below, which uses these as
        # the cut point.
        r"^\s*(recent|latest|popular|previous|other) (articles?|posts?|stories)\s*:?\s*$",
        r"^\s*more (articles?|posts?)\b.*$",
        r"^\s*(previous|next) (post|article)\b",
        r"^\s*posted in\b.*$",
        r"^\s*tags?:\s*$",
        r"^\s*\d+ (comments?|min read)\s*$",
        r"^\s*(copyright|©)\s*\d{4}",
        r"^\s*all rights reserved",
        r"^\s*cookie (policy|settings|preferences)\s*$",
        r"^\s*accept (all )?cookies\s*$",
        r"^\s*advertisement\s*$",
        r"^\s*loading\.{0,3}\s*$",
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

    Applied before hashing so that two copies of one article that differ only
    in indentation produce the SAME hash -- otherwise exact-duplicate
    detection silently misses most real duplicates.
    """
    if not text:
        return ""
    # Unify line endings first: a Windows-served copy of a Unix-served page
    # would otherwise hash differently.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
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
    for line in text.split("\n"):
        if any(pattern.match(line) for pattern in _BOILERPLATE_LINE_PATTERNS):
            removed += 1
            continue
        kept.append(line)
    return _BLANKLINES_RE.sub("\n\n", "\n".join(kept)).strip(), removed


# Headings that mark the start of a "more posts" list at the end of an
# article. Everything from such a heading to the end is chrome, not content.
_LINK_LIST_HEADING_RE = re.compile(
    r"^\s*(recent|latest|popular|related|previous|other|more)\s+"
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


def _extract_primary(html: str, url: str | None) -> tuple[str, str | None]:
    """trafilatura: the extractor whose output we keep."""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            # These four flags are the difference between an article and an
            # article plus its comment section and navigation.
            include_comments=False,
            include_tables=True,     # data tables are often the point
            include_images=False,
            include_links=False,     # we want prose, not link text
            favor_precision=True,    # prefer dropping a paragraph to keeping nav
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

    raw_text, title = _extract_primary(html, url)
    text = normalise_text(raw_text)
    text, boilerplate_removed = strip_boilerplate_lines(text)
    # Remove a trailing "Recent articles" list BEFORE measuring density, so
    # the measurement describes the text we are actually keeping. Measuring
    # first would judge the article on chrome we are about to discard.
    text, link_list_lines_removed = strip_trailing_link_list(text)

    secondary = normalise_text(_extract_secondary(html))
    # Scoped to the kept text -- see compute_link_density for why.
    link_density = compute_link_density(html, keep_text=text)

    chars = len(text)
    words = len(text.split()) if text else 0
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
