"""Extraction and the quality rules.

The junk rules are what "% junk" in the report actually measures, so each
rule gets a test that makes it fire, and the rule NAME is asserted -- the
report groups by those names, and a silent rename would break the breakdown
without breaking anything else.
"""

import re

from app.pipeline.extract import (
    compute_link_density,
    extract,
    normalise_text,
    restore_blockquotes,
    restore_code_indentation,
    restore_list_items,
    strip_boilerplate_lines,
    strip_trailing_link_list,
)

# A realistic article page: nav, sidebar and footer around real prose. The
# extractor's job is to return the <article> and nothing else.
ARTICLE_HTML = """
<html><head><title>Understanding Vector Databases</title></head>
<body>
  <nav><a href="/">Home</a><a href="/blog">Blog</a><a href="/about">About</a></nav>
  <aside class="sidebar">
    <h3>Related posts</h3>
    <ul><li><a href="/a">Post A</a></li><li><a href="/b">Post B</a></li></ul>
  </aside>
  <article>
    <h1>Understanding Vector Databases</h1>
    <p>Vector databases store high-dimensional embeddings and let you search
    them by similarity rather than by exact match. This matters because
    embeddings capture meaning, so a similarity search can find documents
    that are about the same thing without sharing any keywords.</p>
    <p>The core operation is nearest-neighbour search. Doing that exactly is
    expensive in high dimensions, so most systems use an approximate index
    such as HNSW or IVF. The trade-off is recall against latency, and every
    production system tunes that knob differently depending on workload.</p>
    <p>Choosing between them depends on how often your corpus changes, how
    much memory you can spend, and whether you need filtered search. None of
    these questions has a universal answer, which is why benchmarks that
    ignore your access pattern are misleading.</p>
    <p>In practice the index is rarely the bottleneck. Embedding generation
    dominates ingest cost, and query latency is usually dominated by the
    network round trip rather than by the search itself.</p>
  </article>
  <footer>
    <p>Share this</p>
    <p>Copyright 2024 Example Blog. All rights reserved.</p>
  </footer>
</body></html>
"""

NAV_ONLY_HTML = """
<html><body><nav>
""" + "".join(f'<a href="/p{i}">Category link number {i}</a> ' for i in range(60)) + """
</nav></body></html>
"""

STUB_HTML = "<html><body><article><p>Too short.</p></article></body></html>"

EMPTY_HTML = "<html><body></body></html>"


def test_article_text_is_extracted(config):
    result = extract(ARTICLE_HTML, "https://example.com/post", config)
    assert result.ok, f"rejected: {result.failed_rules} {result.detail}"
    assert "nearest-neighbour search" in result.text
    assert result.chars > config.min_article_chars


def test_navigation_is_stripped(config):
    """The core cleaning requirement: nav, sidebar and footer must be gone."""
    result = extract(ARTICLE_HTML, "https://example.com/post", config)
    lowered = result.text.lower()
    for chrome in ("home", "related posts", "post a", "all rights reserved"):
        assert chrome not in lowered, f"boilerplate survived extraction: {chrome!r}"


def test_share_buttons_are_stripped(config):
    result = extract(ARTICLE_HTML, "https://example.com/post", config)
    assert "share this" not in result.text.lower()


def test_too_short_fires_the_named_rule(config):
    """The report groups junk by rule name, so the name is part of the contract."""
    result = extract(STUB_HTML, "https://example.com/x", config)
    assert not result.ok
    assert "too_short" in result.failed_rules
    assert str(config.min_article_chars) in (result.detail or "")


def test_link_heavy_page_is_rejected(config):
    """A page that is mostly links is navigation, not an article."""
    result = extract(NAV_ONLY_HTML, "https://example.com/x", config)
    assert not result.ok
    assert result.failed_rules  # rejected for some named reason


def test_empty_page_is_extraction_failed_not_junk(config):
    """These are different report lines, so they must be distinguishable.

    'Found nothing' and 'found something bad' are separate statuses, and the
    pipeline maps them by looking for this rule name.
    """
    result = extract(EMPTY_HTML, "https://example.com/x", config)
    assert not result.ok
    assert "no_text_extracted" in result.failed_rules


def test_content_hash_is_stable(config):
    """Identical input must hash identically, or exact dedupe never fires."""
    first = extract(ARTICLE_HTML, "https://example.com/a", config)
    second = extract(ARTICLE_HTML, "https://example.com/b", config)
    assert first.content_hash == second.content_hash


def test_whitespace_differences_do_not_change_the_hash(config):
    """The reason hashing runs on NORMALISED text.

    The same article served with different indentation must produce one hash;
    otherwise most real syndicated duplicates slip through layer 2.
    """
    spaced = ARTICLE_HTML.replace("<p>", "<p>\n\n   ")
    assert (
        extract(ARTICLE_HTML, "https://example.com/a", config).content_hash
        == extract(spaced, "https://example.com/a", config).content_hash
    )


def test_long_clean_article_is_not_rejected_for_disagreement(config):
    """Regression: the disagreement rule fired in the wrong direction.

    All five Google Research articles were binned as junk with messages like
    "extractors disagree on length (7373 vs 1851 chars)". Reading the stored
    text showed trafilatura's 7,373 characters were clean and complete --
    readability, the cruder algorithm, had simply given up early.

    Disagreement is only evidence when the PRIMARY is the short one. A long,
    clean primary must survive a short secondary.
    """
    long_article = (
        "<html><body><article><h1>A long technical article</h1>"
        + "<p>This paragraph contains a reasonable quantity of real prose "
        "about a technical subject, and it repeats enough times to build a "
        "document of realistic length for a research blog post. </p>" * 40
        + "</article></body></html>"
    )
    result = extract(long_article, "https://example.com/x", config)
    assert result.ok, f"rejected a clean long article: {result.failed_rules} {result.detail}"
    assert "extractor_disagreement" not in result.failed_rules


def test_secondary_extractor_runs(config):
    """The cross-check must actually produce a number.

    If readability silently returned nothing, `agreement` would be None and
    the extractor_disagreement rule could never fire -- the junk rate would
    look better than it is, which is the failure this guards.
    """
    result = extract(ARTICLE_HTML, "https://example.com/post", config)
    assert result.secondary_chars > 0
    assert result.agreement is not None


def test_link_density_is_computed(config):
    assert compute_link_density(NAV_ONLY_HTML) > 0.5
    assert compute_link_density(ARTICLE_HTML) < 0.5


def test_link_density_on_empty_input():
    assert compute_link_density("") is None


def test_normalise_collapses_whitespace():
    assert normalise_text("a   b\r\n\r\n\r\n\r\nc") == "a b\n\nc"


# ---------------------------------------------------------------------------
# Trailing "Recent articles" lists.
#
# Regression tests for a real failure. On the first live run, three genuine
# Simon Willison articles were rejected as junk at link densities of
# 0.38-0.43. Reading the stored text showed the bodies were clean and a
# "Recent articles" list of other posts had survived extraction. The text
# below is taken from that actual rejected document (record #3).
# ---------------------------------------------------------------------------

REAL_ARTICLE_WITH_LINK_LIST = """29th July 2026
Right now we are in the midst of a historic transition from traditional
public-key algorithms based on EC-based cryptography and RSA, moving over to
new post-quantum algorithms based on novel problems. This is why there are so
many standards like HAWK being considered. If there was ever a perfect time
for a massive new public cryptanalysis capability to come on line, we are in
it.
Recent articles
- OpenAI's accidental cyberattack against Hugging Face - 22nd July 2026
- A Fireside Chat with Cat and Thariq from the Claude Code team - 21st July 2026
- Kimi K3, and what we can still learn from the pelican benchmark - 16th July 2026"""


def test_trailing_link_list_is_removed():
    cleaned, removed = strip_trailing_link_list(REAL_ARTICLE_WITH_LINK_LIST)
    assert removed == 4  # the heading plus three entries
    assert "Recent articles" not in cleaned
    assert "pelican benchmark" not in cleaned
    # The actual article survives intact.
    assert "post-quantum algorithms" in cleaned


def test_article_without_a_link_list_is_untouched():
    text = "A normal article.\nWith two paragraphs and no list at the end."
    cleaned, removed = strip_trailing_link_list(text)
    assert removed == 0
    assert cleaned == text


def test_mid_article_list_is_not_cut():
    """Only TRAILING lists are removed.

    Cutting at a list in the middle would truncate real content, so the scan
    stops at the first non-list line from the end.
    """
    text = (
        "Intro paragraph.\n"
        "- Some bulleted point - 1st January 2020\n"
        "Then the article continues for several more paragraphs and ends here."
    )
    cleaned, removed = strip_trailing_link_list(text)
    assert removed == 0
    assert "continues for several more paragraphs" in cleaned


def test_link_density_is_scoped_to_kept_text():
    """Density must describe the text we KEEP, not the whole page.

    Measuring the entire document counts nav and footer links that extraction
    already removed, which is what wrongly condemned clean articles on
    link-heavy sites.
    """
    html = """
    <html><body>
      <nav>""" + "".join(f'<a href="/{i}">Navigation link {i}</a>' for i in range(40)) + """</nav>
      <article><p>The actual article body has plenty of ordinary prose in it
      and contains no links at all, so its own density should be near zero.</p>
      </article>
    </body></html>
    """
    article_text = (
        "The actual article body has plenty of ordinary prose in it and "
        "contains no links at all, so its own density should be near zero."
    )
    whole_page = compute_link_density(html)
    kept_only = compute_link_density(html, keep_text=article_text)
    assert whole_page > kept_only
    assert kept_only < 0.1


# ---------------------------------------------------------------------------
# Structure preservation.
#
# Reported by the user reviewing a stored Julia Evans post: "the headings are
# missing, only the paragraphs are there, and the indentation is not proper."
# Four separate defects were behind that, each reproduced in isolation before
# being fixed. These tests pin all four.
# ---------------------------------------------------------------------------

HEADED_ARTICLE = (
    "<html><body><article><h1>Main title</h1>"
    + "<p>Opening paragraph with enough text to clear the length floor. </p>" * 6
    + "<h3>First section</h3>"
    + "<p>Section body text that also needs to be reasonably long. </p>" * 6
    + "<pre><code>def hello():\n    return 1</code></pre>"
    + "<h3>Second section</h3>"
    + "<p>More section body text to keep the document above the floor. </p>" * 6
    + "</article></body></html>"
)


def test_headings_survive_extraction(config):
    """Defect 1: `favor_precision=True` was silently dropping every heading.

    Measured on the reported page: it took the heading count from 10 to 0.
    Turning it off restored them and introduced no boilerplate on any of the
    three sites checked.
    """
    result = extract(HEADED_ARTICLE, "https://example.com/x", config)
    assert result.ok, f"{result.failed_rules} {result.detail}"
    headings = [l for l in result.text.splitlines() if l.lstrip().startswith("#")]
    assert len(headings) >= 3, f"expected the headings to survive, got {headings}"
    assert any("First section" in h for h in headings)


def test_code_blocks_survive_extraction(config):
    """Defect 2: plain-text output dropped code fences entirely."""
    result = extract(HEADED_ARTICLE, "https://example.com/x", config)
    assert "```" in result.text, "code fences were lost"
    assert "def hello()" in result.text


def test_heading_wrapped_in_a_self_link_keeps_its_text(config):
    """Defect 3a: static-site generators wrap headings in a self-link.

    <h3 id="x"><a href="#x">text</a></h3> came out as a bare "###" with no
    text, because include_links=False discards the anchor's content.
    """
    html = (
        '<html><body><article><h3 id="s"><a href="#s">Linked heading</a></h3>'
        + "<p>Body text long enough to pass the length floor here. </p>" * 10
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    assert "Linked heading" in result.text


def test_heading_containing_inline_code_is_not_dropped(config):
    """Defect 3b: inline <code> in a heading dropped the WHOLE heading.

    `<h3><code>querystring</code> is cool</h3>` produced nothing at all --
    not an empty heading, no heading. That is why one section vanished from
    the reported article. Confirmed with a minimal fixture: a plain h3
    survives, an h3 containing <code> disappears.
    """
    html = (
        "<html><body><article><h3><code>querystring</code> is cool</h3>"
        + "<p>Body text long enough to pass the length floor here. </p>" * 10
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    assert "querystring is cool" in result.text, (
        "a heading containing inline <code> was dropped entirely"
    )


def test_no_heading_is_emitted_empty(config):
    """A heading marker with no text is worse than no heading at all."""
    html = (
        '<html><body><article><h3 id="s"><a href="#s"><code>fn</code> works</a></h3>'
        + "<p>Body text long enough to pass the length floor here. </p>" * 10
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    for line in result.text.splitlines():
        if line.lstrip().startswith("#"):
            assert line.strip("# ").strip(), f"empty heading emitted: {line!r}"


def test_sentences_split_by_inline_code_are_rejoined():
    """Defect 4: trafilatura breaks a paragraph after every inline code span.

    One sentence arrived as three paragraphs. Verified to come from
    trafilatura itself, not our post-processing.
    """
    broken = "my favourite filter is `querystring`\n\n: in this site sometimes"
    assert "\n\n" not in normalise_text(broken)


def test_genuine_paragraph_breaks_are_preserved():
    """The rejoin must be conservative or it destroys real structure."""
    for text in (
        "End of a thought.\n\nA new paragraph starts here.",
        "introducing a list:\n\n- first item",
        "some prose here\n\n### A heading",
        "and then this.\n\n```\ncode\n```",
    ):
        assert "\n\n" in normalise_text(text), f"wrongly joined: {text!r}"


def test_list_indentation_is_preserved():
    """Defect 5: normalise_text stripped every line, flattening nested lists.

    Correct for plain text, destructive for Markdown -- nested bullets lose
    their nesting and indented blocks stop being blocks.
    """
    nested = "- top level\n    - nested item\n        - deeper still"
    out = normalise_text(nested)
    assert "    - nested item" in out
    assert "        - deeper still" in out


def test_code_block_contents_are_not_reflowed():
    """Indentation inside a fence is semantic in most languages."""
    code = "```\ndef f():\n    if x:\n        return 1\n```"
    out = normalise_text(code)
    assert "    if x:" in out
    assert "        return 1" in out


def test_boilerplate_is_still_stripped_when_markdown_formatted():
    """Boilerplate now arrives as '### Share this', not bare 'Share this'.

    The patterns anchor on line start, so without allowing for Markdown
    prefixes they would silently stop matching once output became Markdown.
    """
    text = "Real article text.\n\n### Share this\n\n- Subscribe to our newsletter"
    cleaned, removed = strip_boilerplate_lines(text)
    assert removed == 2, f"expected both stripped, removed={removed}"
    assert "Real article text." in cleaned


def test_boilerplate_inside_a_code_block_is_kept():
    """A code sample may legitimately contain 'advertisement' or 'loading'.

    Deleting a line from someone's code block corrupts it invisibly.
    """
    text = "Intro.\n\n```\nadvertisement = None\nloading...\n```"
    cleaned, removed = strip_boilerplate_lines(text)
    assert removed == 0
    assert "advertisement = None" in cleaned


# ---------------------------------------------------------------------------
# Inline formatting: links, code indentation, blockquotes.
#
# Second round of reviewer feedback on the same stored article: "the
# hypertexts are just simple text, the code is not indented (Python doesn't
# work without indentation), and text that's in a box and italic is here just
# simple text."
# ---------------------------------------------------------------------------

INDENTED_CODE_HTML = (
    "<html><body><article><h2>Code</h2>"
    + "<p>Here is a class with methods, described at length. </p>" * 8
    + "<pre><code>class Foo:\n    def bar(self):\n        return 1\n</code></pre>"
    + "<p>And some closing prose to keep the length up. </p>" * 8
    + "</article></body></html>"
)


def test_code_indentation_is_restored(config):
    """The most serious of the three: flattened Python is invalid Python.

    trafilatura strips leading whitespace from every line of a code block.
    Verified against the source HTML of a real page: the original has
    `    def approved(self):` and the output had it flush left. A reader
    copying that snippet gets an IndentationError.

    Fixed by taking code text from the DOM, where <pre> preserves whitespace
    by definition.
    """
    result = extract(INDENTED_CODE_HTML, "https://example.com/x", config)
    assert "    def bar(self):" in result.text, (
        f"code indentation was not restored:\n{result.text}"
    )
    assert "        return 1" in result.text


def test_restore_code_indentation_leaves_unmatched_blocks_alone():
    """A wrong replacement is worse than a missing indent.

    If the fenced block cannot be matched back to a <pre> in the DOM, it must
    be returned untouched rather than swapped for something similar.
    """
    text = "```\nsomething not in the html at all\n```"
    out, restored = restore_code_indentation(text, "<html><pre>unrelated</pre></html>")
    assert restored == 0
    assert out == text


def test_restore_code_indentation_is_a_noop_without_code():
    out, restored = restore_code_indentation("just prose", "<html><p>hi</p></html>")
    assert restored == 0
    assert out == "just prose"


def test_links_are_kept_as_markdown(config):
    """Reviewer: hyperlinks arrived as plain text.

    A link is information. "See this post" with the URL stripped is strictly
    less useful than what the author published.
    """
    html = (
        "<html><body><article><h2>T</h2>"
        + "<p>Body text that needs to be long enough to pass the floor. </p>" * 8
        + '<p>Read <a href="https://example.com/post">this post</a> for more.</p>'
        + "<p>More body text to keep the article above the length floor. </p>" * 8
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    assert "[this post](https://example.com/post)" in result.text


def test_link_urls_do_not_inflate_length_or_density(config):
    """Keeping links must not skew the measurements the report is built on.

    Storing [text](url) puts every URL in the raw string. Counting those
    characters would inflate length and link density on exactly the articles
    that cite their sources well -- pushing good writing toward the junk
    threshold for being well-referenced.
    """
    prose = "<p>Plain sentence of prose used as filler content here. </p>" * 10
    plain = f"<html><body><article><h2>T</h2>{prose}<p>See the docs here.</p></article></body></html>"
    linked = (
        "<html><body><article><h2>T</h2>" + prose
        + '<p>See <a href="https://example.com/a/very/long/path/that/goes/on/and/on">the docs</a> here.</p>'
        + "</article></body></html>"
    )
    a = extract(plain, "https://example.com/x", config)
    b = extract(linked, "https://example.com/x", config)
    # The long URL must not add hundreds of characters to the measured length.
    assert abs(a.chars - b.chars) < 40, f"URL inflated length: {a.chars} vs {b.chars}"


def test_blockquotes_are_marked(config):
    """Reviewer: boxed/italic quoted text arrived as ordinary prose.

    This changes attribution, not just appearance: a passage the author was
    quoting from someone else becomes indistinguishable from their own words.
    Measured across six real cached pages -- quote text present in all six,
    '>' marker in none.
    """
    html = (
        "<html><body><article><h2>T</h2>"
        + "<p>Introductory prose that runs on for a while here. </p>" * 8
        + "<blockquote><p>This passage was written by somebody else entirely "
          "and must remain attributable to them.</p></blockquote>"
        + "<p>Closing prose that also runs on for a while here. </p>" * 8
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    quoted = [l for l in result.text.splitlines() if l.lstrip().startswith(">")]
    assert quoted, f"blockquote was not marked:\n{result.text}"
    assert any("somebody else" in l for l in quoted)


def test_restore_blockquotes_ignores_short_quotes():
    """A very short quote is too likely to collide with ordinary prose.

    Mis-marking a sentence as a quotation is a worse error than leaving a
    real quotation unmarked, so the matcher requires a substantial passage.
    """
    text = "Some ordinary prose here."
    out, marked = restore_blockquotes(text, "<html><blockquote>ok</blockquote></html>")
    assert marked == 0
    assert out == text


def test_bold_and_italic_survive(config):
    """Emphasis is authorial intent -- "do NOT do this" reads differently
    without it."""
    html = (
        "<html><body><article><h2>T</h2>"
        + "<p>Filler prose to clear the length floor comfortably. </p>" * 10
        + "<p>This is <strong>important</strong> and this is <em>subtle</em>.</p>"
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    assert "**important**" in result.text
    assert "*subtle*" in result.text


# ---------------------------------------------------------------------------
# Bullet lists split apart by inline code.
#
# Third round of reviewer feedback, and the most serious: "in the real blog it
# has 3 bullets ... while in our harvested blog, it failed to pick all 3 and
# just gave 1". CONTENT loss, not formatting loss -- a reader counting three
# recommendations found one.
# ---------------------------------------------------------------------------

SPLIT_LIST_HTML = (
    "<html><body><article><h2>Filters</h2>"
    + "<p>Some introductory prose that runs long enough to matter. </p>" * 8
    + "<p>The ones I have used so far are:</p>"
    + "<ul>"
    '<li>translating plain text URLs into links '
    "(<code>{{ event.description|urlize }}</code>)</li>"
    '<li>formatting dates (<code>{{ row.date|date:"M j" }}</code>)</li>'
    "<li><code>json_script</code>, which takes a Python dictionary and "
    "converts it to JSON inside a <code>&lt;script&gt;</code> tag</li>"
    "</ul>"
    + "<p>Closing prose that also runs on for a good while here. </p>" * 8
    + "</article></body></html>"
)


def test_all_three_bullets_survive(config):
    """The reported bug: three source bullets became one.

    trafilatura terminates a list item at every inline <code> span, so only
    the first fragment kept its "-" marker and the rest ran together.
    """
    result = extract(SPLIT_LIST_HTML, "https://example.com/x", config)
    bullets = [l for l in result.text.splitlines() if l.lstrip().startswith("- ")]
    assert len(bullets) == 3, (
        f"expected 3 bullets, got {len(bullets)}:\n" + "\n".join(bullets)
    )


def test_each_bullet_keeps_its_own_inline_code(config):
    """The code spans are what split the items; they must still be there."""
    result = extract(SPLIT_LIST_HTML, "https://example.com/x", config)
    bullets = [l for l in result.text.splitlines() if l.lstrip().startswith("- ")]
    assert any("urlize" in b for b in bullets)
    assert any('date:"M j"' in b for b in bullets)
    assert any("json_script" in b for b in bullets)


def test_rejoiner_never_merges_across_list_items():
    """The rejoiner made the bug worse before it was fixed.

    Given items already shredded by trafilatura, it could not tell an item
    boundary from a mid-sentence break and welded them into one line. Any
    block CONTAINING a list marker is now off limits, not just one that
    starts with it.
    """
    text = "- first item ends open\n\n- second item here"
    assert "\n\n" in normalise_text(text)


def test_match_key_absorbs_converter_punctuation_differences():
    """Both real matching failures, pinned.

    The two sides of a list match are the same text rendered by different
    code, and they disagree on punctuation spacing and inserted markup:
      - get_text(' ') gives "json_script , which"; trafilatura gives
        "`json_script`, which"
      - "the HTML as a <script> tag" becomes "a`<script>` tag"
    Either difference silently defeated a literal comparison.
    """
    from app.pipeline.extract import _match_key

    assert _match_key("json_script , which takes") == _match_key(
        "`json_script`, which takes"
    )
    assert _match_key("the HTML as a <script> tag") == _match_key(
        "the HTML as a`<script>` tag"
    )


def test_restore_list_items_leaves_unmatched_lists_alone():
    """Unmatched means untouched -- a wrong replacement could eat prose."""
    text = "Some prose that has nothing to do with any list."
    out, fixed = restore_list_items(
        text, "<html><ul><li>alpha item</li><li>beta item</li></ul></html>"
    )
    assert fixed == 0
    assert out == text


def test_restore_list_items_ignores_single_item_lists():
    """A one-item <ul> is usually layout, not a list a reader would count."""
    out, fixed = restore_list_items(
        "prose", "<html><ul><li>only one</li></ul></html>"
    )
    assert fixed == 0


def test_ordered_lists_keep_their_numbering(config):
    """An <ol> must not come back as bullets: the order is the meaning."""
    html = (
        "<html><body><article><h2>Steps</h2>"
        + "<p>Introductory prose long enough to clear the floor. </p>" * 8
        + "<ol><li>first do <code>this</code></li>"
        "<li>then do <code>that</code></li>"
        "<li>finally check the result</li></ol>"
        + "<p>Closing prose long enough to clear the floor. </p>" * 8
        + "</article></body></html>"
    )
    result = extract(html, "https://example.com/x", config)
    numbered = [
        l for l in result.text.splitlines() if re.match(r"^\s*\d+\.\s", l)
    ]
    assert len(numbered) == 3, f"expected 3 numbered items, got {numbered}"


def test_malformed_html_does_not_raise(config):
    """Real pages are frequently broken. One bad page must not kill a run."""
    for broken in ("<html><body><p>unclosed", "<<>>not html at all", "<p>" * 500):
        result = extract(broken, "https://example.com/x", config)
        assert result is not None  # returned a verdict rather than raising
