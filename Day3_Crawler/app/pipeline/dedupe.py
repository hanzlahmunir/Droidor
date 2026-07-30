"""Duplicate detection in three independent layers.

The task asks for "% duplicates, and how you detected them". The second half
is the interesting part, and it is why this reports three separate numbers
rather than one blended figure:

  LAYER 1  URL          same canonical URL after normalisation.
           Cost: free (a unique index). Catches: tracking-parameter variants,
           http/https, trailing slashes, #fragments.

  LAYER 2  CONTENT      identical SHA-256 of the normalised text.
           Cost: one indexed lookup. Catches: syndication -- the same article
           republished at a different URL, or served at two paths on one site.
           Layer 1 cannot see these; the URLs are genuinely different.

  LAYER 3  NEAR         Jaccard similarity over word shingles, above a
           threshold. Cost: O(n) comparisons against stored articles.
           Catches: a repost with a changed intro, or the same piece lightly
           edited. Neither of the first two layers can see these.

Reporting one merged "% duplicates" would hide which mechanism did the work,
and the mechanisms have very different reliability. Layers 1 and 2 are exact
and need no threshold. Layer 3 is a judgement call with a tunable number, so
its matches are stored WITH the similarity score -- a reviewer can see how
close each call was rather than trusting the threshold blindly.

WHY JACCARD ON SHINGLES, NOT MinHash/LSH.
MinHash exists to make this scale to millions of documents by avoiding
all-pairs comparison. At ~20-100 articles, exact Jaccard is instant and has
no approximation error. Choosing MinHash here would add a false-negative
rate to save time we are not spending. If the corpus grew past a few
thousand, the shingle sets computed here are exactly what MinHash would
consume, so the upgrade is local to this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.statuses import CrawlStatus
from app.storage.models import CrawlRecord

# Tokenisation for shingling: lowercase word characters only. Punctuation and
# case are dropped so that a copy differing only in smart quotes or
# capitalisation still matches -- those differences are formatting, not
# content, and they defeat the exact-hash layer already.
_TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class DuplicateVerdict:
    """Result of the duplicate checks."""

    is_duplicate: bool
    status: CrawlStatus | None = None
    duplicate_of_id: int | None = None
    similarity: float | None = None
    detail: str | None = None


def shingles(text: str, size: int) -> set[str]:
    """Overlapping word n-grams.

    Shingles rather than a bag of words because word frequency alone ignores
    ORDER: two articles on the same topic share most of their vocabulary
    while being completely different pieces of writing. Requiring runs of
    `size` consecutive words to match means a high score reflects copied
    phrasing, not a shared subject.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < size:
        # Too short to shingle: fall back to the token set so very short
        # documents still get a comparison rather than silently scoring 0.
        return set(tokens)
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    """|intersection| / |union|. 1.0 = identical shingle sets, 0.0 = disjoint.

    Jaccard rather than cosine similarity because it is symmetric, needs no
    vector weighting to explain, and its value has a plain-English meaning:
    "the fraction of all distinct 5-word runs that both documents share."
    That is defensible in review in a way a cosine over TF-IDF weights is not.
    """
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if intersection == 0:
        return 0.0
    return intersection / len(left | right)


class DuplicateDetector:
    """Runs the three layers against what is already stored."""

    def __init__(self, session: Session, config: Config) -> None:
        self._session = session
        self._config = config
        # Shingle sets for stored articles, computed once per run. Without
        # this cache, checking N new articles against M stored ones re-shingles
        # every stored article N times.
        self._shingle_cache: dict[int, set[str]] = {}

    def check_url(self, canonical_url: str) -> DuplicateVerdict:
        """Layer 1: have we already processed this exact canonical URL?

        Note this checks crawl_records, not the documents table. A URL that
        was crawled and rejected as junk should not be silently re-crawled on
        every run -- it is still "already seen", just not stored.
        """
        existing = self._session.execute(
            select(CrawlRecord).where(CrawlRecord.canonical_url == canonical_url)
        ).scalar_one_or_none()

        if existing is None:
            return DuplicateVerdict(is_duplicate=False)

        return DuplicateVerdict(
            is_duplicate=True,
            status=CrawlStatus.DUPLICATE_URL,
            duplicate_of_id=existing.id,
            detail=(
                f"already crawled as record #{existing.id} "
                f"with status '{existing.status}'"
            ),
        )

    def check_content(self, content_hash: str) -> DuplicateVerdict:
        """Layer 2: byte-identical text under a different URL.

        Only STORED records are candidates: matching against a record that
        was itself rejected as junk would chain one bad decision into another.
        """
        if not content_hash:
            return DuplicateVerdict(is_duplicate=False)

        existing = self._session.execute(
            select(CrawlRecord)
            .where(CrawlRecord.content_hash == content_hash)
            .where(CrawlRecord.status == CrawlStatus.STORED.value)
            .order_by(CrawlRecord.id)
        ).scalars().first()

        if existing is None:
            return DuplicateVerdict(is_duplicate=False)

        return DuplicateVerdict(
            is_duplicate=True,
            status=CrawlStatus.DUPLICATE_CONTENT,
            duplicate_of_id=existing.id,
            similarity=1.0,
            detail=(
                f"identical text (SHA-256 match) to record #{existing.id} "
                f"at {existing.canonical_url}"
            ),
        )

    def check_near(self, text: str) -> DuplicateVerdict:
        """Layer 3: similar-but-not-identical to something already stored."""
        if not text:
            return DuplicateVerdict(is_duplicate=False)

        candidate = shingles(text, self._config.shingle_size)
        if not candidate:
            return DuplicateVerdict(is_duplicate=False)

        stored = self._session.execute(
            select(CrawlRecord)
            .where(CrawlRecord.status == CrawlStatus.STORED.value)
            .where(CrawlRecord.text.is_not(None))
            .order_by(CrawlRecord.id)
        ).scalars().all()

        best_score = 0.0
        best_record: CrawlRecord | None = None

        for record in stored:
            if record.id not in self._shingle_cache:
                self._shingle_cache[record.id] = shingles(
                    record.text or "", self._config.shingle_size
                )
            score = jaccard(candidate, self._shingle_cache[record.id])
            if score > best_score:
                best_score = score
                best_record = record

        if best_record is not None and best_score >= self._config.near_duplicate_threshold:
            return DuplicateVerdict(
                is_duplicate=True,
                status=CrawlStatus.DUPLICATE_NEAR,
                duplicate_of_id=best_record.id,
                similarity=round(best_score, 4),
                detail=(
                    f"{best_score:.0%} shingle similarity to record "
                    f"#{best_record.id} at {best_record.canonical_url} "
                    f"(threshold {self._config.near_duplicate_threshold:.0%})"
                ),
            )

        # Not a duplicate -- but the best score is returned anyway so the
        # report can show how close the nearest miss was. A corpus whose
        # highest non-duplicate score is 0.84 against a 0.85 threshold is one
        # worth mentioning; the threshold is doing real work there.
        return DuplicateVerdict(
            is_duplicate=False,
            similarity=round(best_score, 4) if best_record is not None else None,
        )
