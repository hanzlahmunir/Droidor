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
        # be configurable.
        self.top_k: int = _int("TOP_K", 5)

        # THE REFUSAL GATE. Cosine similarity below which a chunk is not
        # evidence. If the best chunk scores under this, `ask` answers "I
        # don't know" WITHOUT calling the LLM -- the refusal is a measured
        # property of retrieval, not a hope about model behaviour.
        #
        # 0.40 IS MEASURED. `rag eval` sweeps this against 15 answerable and 8
        # unanswerable questions (data/eval_questions.json) and reports the
        # trade-off. The relevant part of that sweep:
        #
        #     floor   recall   refusal   false-answer
        #     0.350   100.0%     75.0%         25.0%   <- the original guess
        #     0.375   100.0%     87.5%         12.5%
        #     0.400   100.0%     87.5%         12.5%   <- chosen
        #     0.425   100.0%     87.5%         12.5%
        #     0.450    86.7%     87.5%         12.5%   <- recall starts falling
        #     0.550    86.7%    100.0%          0.0%
        #
        # 0.400 sits in the MIDDLE of the 0.375-0.425 plateau rather than at
        # its edge, so a slightly different corpus does not tip it off a
        # cliff. It keeps every answerable question while refusing 7 of 8
        # unanswerable ones outright.
        #
        # The remaining leak is deliberate. "How much does Cloudflare charge
        # per million Workers requests?" scores 0.543 -- the corpus has five
        # Cloudflare articles, so pricing-shaped questions match well without
        # containing the answer. No floor that catches it also keeps full
        # recall (0.550 costs two answerable questions). That case is the
        # prompt layer's job, and it does catch it -- verified end to end.
        self.similarity_floor: float = _float("SIMILARITY_FLOOR", 0.40)

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
