"""Turn text into vectors. The only module that loads the model.

WHY THIS IS A CLASS BEHIND AN INTERFACE. Loading a sentence-transformer takes
several seconds and ~90MB of RAM, which is fine once per process and
unacceptable once per call. More importantly, keeping it behind a small
interface means every other module can be tested with a fake embedder that
returns fixed vectors -- so the retrieval logic, the threshold and the refusal
gate are all testable with no model, no download and no network.

TWO MEASURED FACTS DRIVE THIS MODULE.

  1. all-MiniLM-L6-v2 truncates at 256 TOKENS, not the 512 its tokenizer
     advertises. Text past that point contributes nothing to the vector and
     no error is raised -- the tail is simply unsearchable. See count_tokens
     and the `truncated` figure that ingest reports.

  2. Queries and documents must be embedded the same way. This model is
     symmetric (unlike e5/bge, which require "query:" / "passage:" prefixes),
     so no prefix is applied. Applying one to only half a corpus is a classic
     silent-degradation bug: everything still works, results just get worse.

NORMALISATION. Vectors are returned L2-normalised, which makes the dot product
equal to cosine similarity. Chroma's cosine space expects this, and it is what
makes the configured similarity floor mean what it says.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from app.config import Config


class Embedder(Protocol):
    """The contract the rest of the system depends on.

    Deliberately tiny. Anything that needs embeddings takes one of these, so
    tests can pass a deterministic fake and never load a model.
    """

    @property
    def dimension(self) -> int:
        """Length of the vectors this embedder produces."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus chunks, in the order given."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single question."""
        ...


class SentenceTransformerEmbedder:
    """The real embedder, wrapping sentence-transformers.

    The model is loaded lazily on first use rather than in __init__, so that
    constructing a Config and an Embedder stays cheap -- `stats` and `--help`
    should not pay for a model load they never use.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._model = None
        self._dimension: int | None = None

    def _load(self):
        if self._model is None:
            # Imported here, not at module top level, so that importing this
            # module (which the CLI always does) does not drag in torch. That
            # import alone costs seconds.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._config.embedding_model)

            # Trust the model's own reported window over anything configured.
            # The config value is a declared expectation; this is the truth,
            # and they disagreeing silently is exactly how the 12.6%
            # truncation went unnoticed.
            reported = getattr(self._model, "max_seq_length", None)
            if reported:
                self._max_tokens = int(reported)
            else:
                self._max_tokens = self._config.embedding_max_tokens

            self._dimension = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dimension(self) -> int:
        self._load()
        assert self._dimension is not None
        return self._dimension

    @property
    def max_tokens(self) -> int:
        """The model's real input window, in tokens."""
        self._load()
        return self._max_tokens

    def count_tokens(self, text: str) -> int:
        """Token length of `text` under the model's own tokenizer.

        Used by ingest to report how many chunks exceed the window. Character
        length is not a usable proxy: measured across this corpus, prose runs
        ~3.9 chars/token while link-dense text runs as low as 1.6.
        """
        model = self._load()
        return len(model.tokenizer.encode(text, add_special_tokens=True))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(
            list(texts),
            batch_size=self._config.embedding_batch_size,
            # L2-normalised, so dot product == cosine similarity and Chroma's
            # cosine distance behaves as the floor in config assumes.
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed a question.

        Identical treatment to documents -- same model, same normalisation, no
        prefix. This model is symmetric; adding an asymmetric prefix here
        without also changing ingestion would degrade every result while
        raising no error at all.
        """
        return self.embed_documents([text])[0]


class FakeEmbedder:
    """A deterministic embedder for tests. No model, no network, no download.

    Vectors come from a hash of the text, so the same string always embeds to
    the same vector and different strings embed differently. That is enough to
    test the parts that matter -- storage round-trips, ordering by score, the
    threshold, the refusal -- without the several-second model load that would
    otherwise be paid by every test.

    It does NOT produce semantically meaningful vectors, and nothing that
    depends on real semantics should be tested with it. Those properties are
    measured by `eval` against the real model instead.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        import hashlib
        import math

        # A stable digest expanded to the required length. hashlib rather than
        # hash() because the latter is salted per process, which would make
        # tests pass or fail depending on the run.
        raw = hashlib.sha256(text.encode("utf-8")).digest()
        values = [
            (raw[i % len(raw)] - 128) / 128.0 for i in range(self._dimension)
        ]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
