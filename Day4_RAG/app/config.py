"""Central configuration, read from the environment.

Every number the pipeline uses lives here rather than as a magic value buried
in the module that happens to need it. Day 3 established this pattern for the
crawler's thresholds; the reasoning carries over and the task states it
outright:

    "Chunk size and top-k must be config values, not hardcoded -- you'll be
     changing them later this week."

So CHUNK_SIZE, CHUNK_OVERLAP and TOP_K are env-driven by requirement. The rest
are here for the same underlying reason: retrieval quality is *tuned*, and a
tuning run that needs a code edit between each trial is a tuning run nobody
does. `eval` sweeps these values, which is only possible because they are read
from the environment rather than compiled in.

The one secret is GROQ_API_KEY. Unlike Day 3, it does NOT degrade gracefully:
without it there is no answer to generate. Retrieval still works, and `ask`
says which half is missing rather than failing with a bare KeyError.
"""

import os

from dotenv import load_dotenv

# Load .env into os.environ if present. Real deployments set env vars
# directly, so a missing .env file is not an error.
load_dotenv()


def _int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to a default."""
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


class ConfigError(ValueError):
    """Raised when a config value is present but unusable.

    Separate from a missing value: "CHUNK_OVERLAP=2000 with CHUNK_SIZE=1000"
    is a typo that would otherwise produce an infinite loop in the chunker at
    ingest time, thousands of chunks in, rather than an error at startup.
    """


class Config:
    """Runtime settings. Instantiated once at entry and passed down."""

    def __init__(self) -> None:
        # ---------- Where the corpus comes from ----------
        # The Day 1 API, addressed over HTTP by its compose hostname. We GET
        # /documents rather than reading the documents table directly, for the
        # same reason Day 3 POSTed instead of INSERTing: going around the API
        # leaves its contract -- pagination, ordering, the response schema --
        # unexercised, and silently forks the definition of "a document".
        self.api_base_url: str = os.environ.get(
            "API_BASE_URL", "http://api:8000"
        ).rstrip("/")

        # Day 1 caps `limit` at 100 (le=100), so ingestion pages. Kept at the
        # cap rather than below it: fewer round-trips, and the boundary is
        # exercised on every run instead of only when the corpus grows.
        self.corpus_page_size: int = _int("CORPUS_PAGE_SIZE", 100)

        self.request_timeout_seconds: float = _float("REQUEST_TIMEOUT_SECONDS", 30.0)

        # ---------- Chunking ----------
        # Target characters per chunk, not tokens. Characters because the
        # chunker splits Markdown text and never sees the tokeniser, so a
        # character budget is the honest unit -- a token estimate here would
        # be a guess dressed as a measurement.
        #
        # 700 IS A MEASURED VALUE, NOT A GUESS.
        #
        # all-MiniLM-L6-v2 truncates at 256 tokens and silently discards
        # everything past it -- the tail of an over-long chunk contributes
        # nothing to its vector and is unsearchable, with no error raised.
        #
        # Sweeping this value over the real 20-article corpus, counting tokens
        # with the model's own tokenizer:
        #
        #     chars   chunks   truncated
        #      500      556       1.1%
        #      600      475       1.5%
        #      700      412       2.7%     <- chosen
        #      800      352       5.1%
        #      900      321       8.1%
        #     1000      301      12.6%     <- the original guess
        #
        # 700 keeps truncation marginal while avoiding the chunk explosion of
        # 500. The residual 2.7% is NOT fixable by lowering this further: it is
        # entirely (a) code blocks kept whole on purpose, and (b) link-dense
        # prose, where URLs tokenise at ~1.6 chars/token against prose's ~3.9.
        # `ingest` reports the count rather than hiding it.
        self.chunk_size: int = _int("CHUNK_SIZE", 700)

        # Characters repeated from the end of one chunk at the start of the
        # next. Overlap exists because a sentence answering the question may
        # straddle a boundary; without it, that sentence is in neither chunk
        # in full and is retrievable from neither.
        self.chunk_overlap: int = _int("CHUNK_OVERLAP", 150)

        # A chunk shorter than this is dropped. Below roughly this length a
        # chunk is a stray heading, a page-navigation fragment or a one-line
        # caption: it embeds to something almost arbitrary and, because it is
        # short, can score misleadingly high against a short question.
        self.min_chunk_chars: int = _int("MIN_CHUNK_CHARS", 80)

        # Fenced code blocks are kept whole even when they exceed chunk_size
        # -- half a code block is two invalid fragments, and Day 3 went to
        # real trouble to preserve code indentation and fences, which it would
        # be careless to discard here. This caps that exemption: a code block
        # larger than this is split anyway rather than sent as one enormous
        # chunk that crowds out every other result.
        self.max_code_block_chars: int = _int("MAX_CODE_BLOCK_CHARS", 4000)

        # ---------- Embeddings ----------
        # all-MiniLM-L6-v2: 384 dimensions, CPU-friendly, no API key. The
        # dimension matters downstream -- a collection built with one model
        # cannot be queried with another -- so the model name is recorded in
        # the collection metadata and `ingest` refuses a mismatch rather than
        # returning quietly meaningless neighbours.
        self.embedding_model: str = os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )

        # The model's real input window, in TOKENS, measured from the loaded
        # model rather than assumed: sentence-transformers reports
        # max_seq_length = 256 for all-MiniLM-L6-v2, which is half the 512 its
        # tokenizer advertises. Getting this wrong in the optimistic direction
        # is invisible -- text past the limit is dropped with no error.
        #
        # Expressed in tokens, not characters, because the conversion is not
        # stable: measured across this corpus, prose runs ~3.9 chars/token
        # while link-dense text runs as low as 1.6. A character budget that
        # looks safe for prose is therefore wrong by more than 2x for a
        # paragraph full of URLs.
        self.embedding_max_tokens: int = _int("EMBEDDING_MAX_TOKENS", 256)

        # Batch size for encoding. Purely a throughput/memory trade-off.
        self.embedding_batch_size: int = _int("EMBEDDING_BATCH_SIZE", 32)

        # ---------- Retrieval ----------
        # How many chunks the vector search returns. Required by the task to
        # be configurable -- and it turned out to need changing, exactly as
        # the task predicted, once the corpus grew.
        #
        # 12 IS MEASURED, at 112 articles / 2183 chunks:
        #
        #     top_k   recall@0.425   refusal
        #        5        96.7%       53.8%
        #        8        96.7%       53.8%
        #       12       100.0%       53.8%   <- chosen
        #       16       100.0%       53.8%   (identical -- saturated)
        #       20       100.0%       53.8%   (identical)
        #
        # At 20 articles this value was irrelevant: every question had one
        # obvious home and 5 was plenty. At 112 it is not. "What is the
        # Cloudflare CI SDK built on top of?" retrieves four Cloudflare
        # MARKETING posts scoring 0.575-0.613 ahead of the article that
        # actually answers it at 0.568 -- 25 Cloudflare articles share so much
        # boilerplate vocabulary that the embedding barely separates them. At
        # top_k=5 the right chunk is the last one in; at 12 it is comfortably
        # inside.
        #
        # Raising it costs nothing in refusal, because the false positives
        # here score HIGH rather than ranking low -- more results cannot add a
        # false positive that a floor was already going to admit. It saturates
        # at 12, so this is the value where recall is bought and nothing
        # further is gained.
        self.top_k: int = _int("TOP_K", 12)

        # THE REFUSAL GATE. Cosine similarity below which a chunk is not
        # evidence. If the best chunk scores under this, `ask` answers "I
        # don't know" WITHOUT calling the LLM -- the refusal is a measured
        # property of retrieval, not a hope about model behaviour.
        #
        # 0.425 IS MEASURED, at 112 articles / 2183 chunks, against 30
        # answerable and 13 unanswerable questions.
        #
        #     floor   recall   refusal   false-answer
        #     0.400   100.0%     46.2%         53.8%
        #     0.425   100.0%     53.8%         46.2%   <- chosen
        #     0.500    90.0%     61.5%         38.5%
        #     0.525    86.7%     69.2%         30.8%
        #     0.575    73.3%     84.6%         15.4%   <- "best balanced"
        #
        # WHAT CHANGED FROM THE 20-ARTICLE VERSION, AND WHY IT MATTERS.
        # This floor was 0.40, chosen when the corpus was 20 articles and the
        # floor caught 7 of 8 unanswerable questions on its own. That number
        # did not survive contact with a real corpus: on the same questions at
        # 112 articles the false-answer rate went 12.5% -> 37.5% with no code
        # change at all. "What were the main causes of the 2008 financial
        # crisis?" scored 0.24 at 20 articles and 0.404 at 112, where it would
        # cite a DDoS threat report. More text means more accidental matches.
        #
        # SO THE FLOOR'S JOB HAS CHANGED. It is no longer the primary defence;
        # it is a cheap pre-filter that kills obvious nonsense (quicksort,
        # Formula One) for free, before any token is spent. It CANNOT separate
        # the hard cases: a question about a real, densely-covered article
        # whose specific fact is absent scores 0.50-0.70, which is exactly
        # where genuine answers live. Six such questions are in the eval set
        # by construction, scoring up to 0.702.
        #
        # 0.425 is the highest floor that still keeps 100% recall. Going
        # higher buys refusal by refusing real questions -- 0.575 would reject
        # the Steve Yegge quote (0.512) and the MiniMax hardware question
        # (0.554). The `balanced` column prefers 0.575, but that metric weighs
        # a missed answer exactly as heavily as a fabricated one, which is the
        # wrong trade for a system whose stated contract is "cites its sources
        # or says I don't know".
        #
        # The hard cases are the PROMPT layer's job, and it holds: all four
        # near-misses tested end to end were refused, including the 0.702
        # SymptomAI benchmark question. That is the argument for two layers,
        # and it gets stronger with corpus size, not weaker -- a
        # threshold-only system would now fabricate answers to 46% of the
        # unanswerable set.
        self.similarity_floor: float = _float("SIMILARITY_FLOOR", 0.425)

        # Total characters of retrieved chunks passed to the answer model.
        # Bounds cost and latency, and stops one long chunk from consuming the
        # whole context. Chunks are added in score order, best first, so
        # trimming drops the weakest evidence.
        self.max_context_chars: int = _int("MAX_CONTEXT_CHARS", 8000)

        # ---------- Answer generation ----------
        self.groq_api_key: str | None = os.environ.get("GROQ_API_KEY") or None
        # Same model Day 2 measured as reliable for instruction-following.
        self.answer_model: str = os.environ.get("ANSWER_MODEL", "openai/gpt-oss-120b")
        # Low but not zero: near-deterministic answers, so the same question
        # over the same chunks gives the same result and the eval numbers mean
        # something across runs.
        self.answer_temperature: float = _float("ANSWER_TEMPERATURE", 0.1)
        self.answer_max_tokens: int = _int("ANSWER_MAX_TOKENS", 800)

        # ---------- Storage ----------
        # Chroma persists to a directory, not a database server. Mounted as a
        # volume in compose so ingestion survives `docker compose down`.
        self.chroma_dir: str = os.environ.get("CHROMA_DIR", "chroma_db")
        self.collection_name: str = os.environ.get("COLLECTION_NAME", "articles")

        # ---------- Paths ----------
        self.eval_questions_path: str = os.environ.get(
            "EVAL_QUESTIONS_PATH", "data/eval_questions.json"
        )
        self.report_dir: str = os.environ.get("REPORT_DIR", "data/reports")

        self._validate()

    def _validate(self) -> None:
        """Reject combinations that would fail later, and less clearly.

        Each check here corresponds to a real failure mode, and every one of
        them would otherwise surface far from its cause -- mid-ingest, or as
        retrieval that returns plausible nonsense.
        """
        if self.chunk_size <= 0:
            raise ConfigError(f"CHUNK_SIZE must be positive, got {self.chunk_size}")

        if self.chunk_overlap < 0:
            raise ConfigError(
                f"CHUNK_OVERLAP cannot be negative, got {self.chunk_overlap}"
            )

        # The important one. If overlap >= size, each chunk begins at or
        # before the previous chunk's start, so the chunker never advances:
        # an infinite loop producing identical chunks until memory runs out.
        # Caught here, at startup, with the two numbers named.
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be smaller than "
                f"CHUNK_SIZE ({self.chunk_size}) -- otherwise chunking cannot "
                f"advance through the text and would loop forever."
            )

        if self.min_chunk_chars >= self.chunk_size:
            raise ConfigError(
                f"MIN_CHUNK_CHARS ({self.min_chunk_chars}) must be smaller "
                f"than CHUNK_SIZE ({self.chunk_size}), or every chunk is "
                f"discarded as too short and the corpus ingests to nothing."
            )

        if self.top_k <= 0:
            raise ConfigError(f"TOP_K must be positive, got {self.top_k}")

        # Cosine similarity over normalised embeddings is in [-1, 1]. A floor
        # above 1 refuses everything; below -1 refuses nothing, silently
        # disabling the gate this system is judged on.
        if not -1.0 <= self.similarity_floor <= 1.0:
            raise ConfigError(
                f"SIMILARITY_FLOOR must be between -1 and 1 (cosine "
                f"similarity), got {self.similarity_floor}"
            )

        if self.max_context_chars <= 0:
            raise ConfigError(
                f"MAX_CONTEXT_CHARS must be positive, got {self.max_context_chars}"
            )

    def describe(self) -> dict[str, object]:
        """The settings that affect retrieval results.

        Reported by `stats` and written into the eval report, so a set of
        numbers can always be traced to the configuration that produced it.
        Day 3's lesson: a report that does not state what it measured against
        drifts away from the code and becomes a lie.
        """
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "min_chunk_chars": self.min_chunk_chars,
            "embedding_model": self.embedding_model,
            "top_k": self.top_k,
            "similarity_floor": self.similarity_floor,
            "max_context_chars": self.max_context_chars,
            "answer_model": self.answer_model,
        }
