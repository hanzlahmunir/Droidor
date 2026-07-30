"""Near-duplicate similarity maths.

The pure functions are tested here without a database. The URL and content
layers are exact lookups against Postgres and are exercised by the live run;
this file covers the layer that involves a judgement call, because that is
the one whose behaviour is not self-evident.
"""

from app.pipeline.dedupe import jaccard, shingles

ARTICLE = (
    "Vector databases store high dimensional embeddings and let you search "
    "them by similarity rather than by exact keyword match. The core "
    "operation is nearest neighbour search, which is expensive to do exactly "
    "in high dimensions, so most systems use an approximate index."
)

# The same article with a changed opening sentence -- the classic repost.
REPOST = (
    "Here is a quick introduction. Vector databases store high dimensional "
    "embeddings and let you search them by similarity rather than by exact "
    "keyword match. The core operation is nearest neighbour search, which is "
    "expensive to do exactly in high dimensions, so most systems use an "
    "approximate index."
)

# Same TOPIC, different writing. Must NOT be called a duplicate.
DIFFERENT = (
    "Graph databases model relationships as first class citizens. Traversing "
    "edges is cheap, which makes them a good fit for recommendation systems "
    "and fraud detection where the shape of the connections is the signal."
)


def test_identical_text_scores_one():
    left = shingles(ARTICLE, 5)
    assert jaccard(left, left) == 1.0


def test_repost_scores_high(config):
    score = jaccard(shingles(ARTICLE, 5), shingles(REPOST, 5))
    assert score >= config.near_duplicate_threshold, (
        f"a repost with a changed intro scored {score:.2f}, below the "
        f"{config.near_duplicate_threshold} threshold -- it would be missed"
    )


def test_different_articles_score_low(config):
    score = jaccard(shingles(ARTICLE, 5), shingles(DIFFERENT, 5))
    assert score < config.near_duplicate_threshold


def test_same_topic_different_words_are_not_duplicates():
    """Why shingles rather than a bag of words.

    Two articles on one subject share most of their vocabulary. Requiring
    runs of five consecutive words to match means a high score reflects
    copied phrasing, not a shared topic.
    """
    a = "the cat sat on the mat while the dog watched from the doorway"
    b = "the dog sat on the doorway while the cat watched from the mat"
    assert jaccard(shingles(a, 5), shingles(b, 5)) < 0.3


def test_disjoint_texts_score_zero():
    assert jaccard(shingles("alpha beta gamma delta epsilon", 5),
                   shingles("one two three four five", 5)) == 0.0


def test_empty_input_scores_zero():
    assert jaccard(set(), shingles(ARTICLE, 5)) == 0.0
    assert jaccard(shingles("", 5), shingles("", 5)) == 0.0


def test_short_text_falls_back_to_tokens():
    """Text shorter than one shingle must still produce a comparable set,
    rather than an empty set that silently scores 0 against everything."""
    assert shingles("only three words", 5) == {"only", "three", "words"}


def test_shingling_is_case_and_punctuation_insensitive():
    """Formatting differences already defeat the exact-hash layer; the near
    layer must not be defeated by them too."""
    assert (
        shingles("The Cat, Sat! On The Mat.", 3)
        == shingles("the cat sat on the mat", 3)
    )


def test_jaccard_is_symmetric():
    left, right = shingles(ARTICLE, 5), shingles(REPOST, 5)
    assert jaccard(left, right) == jaccard(right, left)
