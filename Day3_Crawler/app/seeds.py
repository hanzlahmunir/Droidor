"""The five seed feeds for the demo run.

CHOSEN FOR THREE PROPERTIES, not for topic preference:

  1. Permissive robots.txt for a well-behaved crawler. A demo that reports
     "5 of 5 feeds disallowed" proves the robots gate works but produces no
     articles to measure.
  2. No login, no paywall. The brief puts both out of scope, so seeding with
     a metered publisher would mean the run is mostly PAYWALL_PARTIAL.
  3. Genuinely different site builders -- a static-site generator, a
     WordPress blog, an organisation's newsroom. Extraction difficulty varies
     enormously by CMS, and five feeds from one platform would make the
     extractor look better than it is.

Topic: software engineering and AI, which keeps the corpus coherent enough
that the near-duplicate threshold is doing real work rather than comparing
unrelated subjects.

These are a DEFAULT, not a hard-coded limit: `crawl` takes any URL and
`feed` takes any feed.
"""

# (label, feed URL). The label becomes the `source` field on stored documents.
SEED_FEEDS: tuple[tuple[str, str], ...] = (
    # Static-site generator, clean semantic HTML, generous robots.txt.
    ("Julia Evans", "https://jvns.ca/atom.xml"),
    # Long-form engineering writing, different generator again.
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    # Organisation newsroom: heavier templates, more chrome to strip, which
    # is what makes it a useful test rather than an easy one.
    ("Mozilla Hacks", "https://hacks.mozilla.org/feed/"),
    # WordPress, the most common blogging platform, with its characteristic
    # sidebar and "related posts" boilerplate.
    ("Cloudflare Blog", "https://blog.cloudflare.com/rss/"),
    # Academic/research writing, longer articles, different date markup.
    ("Google Research", "https://research.google/blog/rss/"),
)
