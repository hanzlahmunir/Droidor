"""Turn retrieved chunks into an answer with citations.

THE SECOND LAYER OF THE REFUSAL. The similarity floor in retriever.py is the
first and the measurable one. This is the second: chunks can clear the floor
because they share a topic with the question while not containing the answer
("How much does Cloudflare charge per million requests?" retrieves plenty of
Cloudflare prose). So the prompt requires the model to abstain in that case.

CITATIONS ARE VALIDATED, NOT TRUSTED. Whatever the model emits as [1], [2] is
checked against the sources actually sent. A citation pointing at [7] when six
sources were provided is dropped -- a fabricated source is worse than none,
because it looks like provenance while being invented.

THE ONE HALLUCINATION THIS SYSTEM PRODUCED, AND THE RULE IT ADDED.
Asked "Which Django version does the author recommend for production?", the
model answered:

    "The author points to the Django 6.0 documentation (e.g. the performance
     and models topics are linked to /docs.djangoproject.com/en/6.0/),
     indicating they recommend using Django 6.0 in production [3][6]."

"6.0" appears in that article ONLY as a path segment inside documentation
links -- docs.djangoproject.com/en/6.0/topics/performance/. The author never
recommends a version. The model read a URL as a claim, and cited real chunks
for it, which is what makes this failure mode dangerous: it looks sourced.

It is intermittent -- 1 in 10 runs at temperature 0.1 -- which is exactly why
it survived earlier testing.

Rule 5 below was added for it: only PROSE states facts, and a link target is
not something the author said. MEASURED, THE RULE DID NOT FIX IT: 1 in 10
before, 1 in 10 after (10 trials each), with the rule verified present in the
prompt the container sends. The rule is kept because it is correct and costs
nothing, but it is documentation, not a fix.

WHAT THIS SAYS ABOUT THE ARCHITECTURE. The prompt layer is a probabilistic
filter, not a guarantee. It catches the near-miss questions reliably (6/6 on
questions scoring up to 0.702) but it cannot be relied on for a specific
failure mode, because "follow this instruction every time" is not something a
sampled model does. A deterministic fix would have to live in code -- e.g.
stripping URLs from chunk text before they reach the model, so a version
number inside a documentation address is never visible as evidence. That is a
real change with its own cost (links are sometimes the answer) and is not
made here; it is written up in the README as the known limitation it is.

A MEASURED PROPERTY OF THIS MODEL. openai/gpt-oss-120b is a REASONING model:
it spends completion tokens on a hidden `reasoning` field before writing
`content`. Measured on a RAG-shaped call, it used 251-273 tokens for an answer
of two sentences, and at max_tokens=100 it returned finish_reason='length'
with content EMPTY -- the reasoning consumed the entire budget. An empty
string rendered as an answer looks like a model that had nothing to say, so
that case is detected and reported rather than displayed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import Config
from app.retriever import RetrievedChunk, build_context

# The refusal string. One constant, used by the prompt, the code paths that
# refuse before ever calling a model, and the tests -- so "I don't know" is
# literally the same text everywhere and `eval` can detect it by comparison
# rather than by guessing at phrasing.
I_DONT_KNOW = "I don't know."

SYSTEM_PROMPT = f"""You answer questions using ONLY the numbered sources provided.

Rules:
1. Use only information present in the sources. Do not add anything you know
   independently, however confident you are about it.
2. Cite every claim with the bracketed number of its source, like [1] or [2].
3. If the sources do not contain the answer, reply with exactly:
   {I_DONT_KNOW}
   Do not guess, do not infer beyond what is written, and do not answer a
   nearby question instead of the one asked.
4. Sources sharing a topic with the question is NOT the same as containing
   the answer. If they discuss the subject but omit the specific fact asked
   for, that is still {I_DONT_KNOW}
5. Only PROSE states facts. A URL, a link target, a version number inside a
   documentation address, a file path or a citation marker is not a claim the
   author made. If the only support for an answer is what a link points at
   rather than what the text says, the answer is {I_DONT_KNOW}
6. Be concise. Two or three sentences is usually right.
"""


@dataclass
class Answer:
    """A generated answer and the sources behind it."""

    text: str
    citations: list[RetrievedChunk] = field(default_factory=list)
    refused: bool = False
    # Set when the refusal came from the similarity floor rather than the
    # model, so the caller can say WHICH layer refused.
    refused_before_llm: bool = False
    reason: str = ""

    @property
    def cited_sources(self) -> list[str]:
        """Unique article citations, in the order first cited."""
        seen: dict[str, None] = {}
        for chunk in self.citations:
            seen.setdefault(chunk.citation(), None)
        return list(seen)


class AnswerError(RuntimeError):
    """Answer generation failed for a reason the user can act on."""


def refuse(reason: str, *, before_llm: bool = True) -> Answer:
    """Build a refusal. One construction point so the wording never drifts."""
    return Answer(
        text=I_DONT_KNOW,
        citations=[],
        refused=True,
        refused_before_llm=before_llm,
        reason=reason,
    )


# Citation markers this model actually emits, all three observed on real
# answers from openai/gpt-oss-120b despite the prompt asking for "[1]":
#
#     [1]  [1, 2]  [4][5]        the requested form
#     【1】                        CJK brackets
#     【1†L1-L4】                  CJK brackets with a line-range suffix
#
# The last two come from the model's training on tools that use that
# convention. Matching only the requested form was a real bug: the answer was
# correct and well-sourced, every citation was dropped as unrecognised, and
# the output carried "No valid citations -- treat this answer with suspicion"
# on a perfectly good answer. Worth noting the failure was in the SAFE
# direction -- it under-trusted rather than fabricating -- but it made the
# citation display useless for most answers.
_CITATION_PATTERN = re.compile(r"[\[【]\s*([\d,\s]+?)\s*(?:†[^\]】]*)?[\]】]")


def extract_citation_indices(text: str) -> set[int]:
    """Find citation markers in the model's answer, in any form it emits.

    See _CITATION_PATTERN: this model mixes ASCII and CJK brackets freely
    within a single answer, so a matcher that understands only one silently
    under-counts and drops real citations.
    """
    indices: set[int] = set()
    for group in _CITATION_PATTERN.findall(text):
        for part in group.split(","):
            part = part.strip()
            if part.isdigit():
                indices.add(int(part))
    return indices


def validate_citations(
    text: str, sources: list[RetrievedChunk]
) -> tuple[str, list[RetrievedChunk]]:
    """Keep only citations that point at a source we actually sent.

    A model citing [7] when six sources were provided has invented a
    reference. Dropping the marker from the text is the honest repair: the
    claim may still be supported by the other sources, but the specific
    pointer is false and rendering it would fabricate provenance.
    """
    valid_range = range(1, len(sources) + 1)
    cited = extract_citation_indices(text)
    invalid = {i for i in cited if i not in valid_range}

    def _drop_invalid(match: re.Match) -> str:
        """Remove a marker only if every index inside it is invalid.

        Rewritten through the same pattern that found the markers, rather than
        by string replacement: a literal `text.replace("[7]", "")` cannot see
        the CJK forms, so an invented 【7†L1-L4】 would survive the cleaning and
        be shown to the reader as though it were real provenance.

        A mixed marker like [2, 9] keeps its valid part -- dropping the whole
        thing would discard the genuine citation alongside the invented one.
        """
        numbers = [p.strip() for p in match.group(1).split(",") if p.strip().isdigit()]
        kept = [n for n in numbers if int(n) in valid_range]
        if not kept:
            return ""
        return f"[{', '.join(kept)}]"

    cleaned = _CITATION_PATTERN.sub(_drop_invalid, text) if invalid else text

    used = [sources[i - 1] for i in sorted(cited & set(valid_range))]
    return cleaned.strip(), used


def looks_like_refusal(text: str) -> bool:
    """Did the model abstain?

    Two competing requirements, and getting the balance wrong breaks `eval` in
    opposite directions:

      - Too strict, and a refusal phrased "I don't know" without the full stop
        is counted as an ANSWER, understating the refusal rate. Models vary
        punctuation, capitalisation and apostrophe style even when told to
        reply exactly, so the comparison has to be normalised.

      - Too loose, and a real answer that merely OPENS with the phrase --
        "I don't know much about X, but the sources say Y" -- is counted as a
        refusal, overstating it. A prefix match does exactly this.

    So: the refusal must be the whole answer, which is what the prompt asks
    for, rather than merely its opening.
    """
    normalised = text.strip().lower().rstrip(".!").replace("’", "'")
    return normalised in ("i don't know", "i do not know")


def generate_answer(
    query: str,
    chunks: list[RetrievedChunk],
    config: Config,
    *,
    client=None,
) -> Answer:
    """Ask the model to answer from `chunks`, then validate what comes back.

    `client` is injectable so tests can supply a stub and never call an API.
    """
    if not chunks:
        return refuse("No chunks cleared the similarity floor.")

    if client is None:
        if not config.groq_api_key:
            # Retrieval worked; only generation is unavailable. Saying exactly
            # that is more useful than a stack trace from the SDK, and the
            # caller can still show the retrieved sources.
            raise AnswerError(
                "GROQ_API_KEY is not set, so no answer can be generated. "
                "Retrieval still works -- run with --show-chunks to see what "
                "was found. Set the key in .env to enable answers."
            )
        from groq import Groq

        client = Groq(api_key=config.groq_api_key)

    context, used = build_context(chunks, config)

    try:
        response = client.chat.completions.create(
            model=config.answer_model,
            temperature=config.answer_temperature,
            max_tokens=config.answer_max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Sources:\n\n{context}\n\nQuestion: {query}",
                },
            ],
        )
    except Exception as exc:
        raise AnswerError(f"The answer model call failed: {exc}") from exc

    choice = response.choices[0]
    raw = (choice.message.content or "").strip()

    if not raw:
        # MEASURED FAILURE MODE, not a hypothetical. This is a reasoning model:
        # it writes to a hidden `reasoning` field first, and if max_tokens runs
        # out there, `content` comes back empty with finish_reason='length'.
        # Rendering that as the answer would show the user a blank reply.
        finish = getattr(choice, "finish_reason", "unknown")
        if finish == "length":
            raise AnswerError(
                f"The model used its entire {config.answer_max_tokens}-token "
                f"budget on reasoning and produced no answer. Raise "
                f"ANSWER_MAX_TOKENS (measured: a RAG answer needs ~275)."
            )
        raise AnswerError(
            f"The model returned an empty answer (finish_reason={finish})."
        )

    if looks_like_refusal(raw):
        # The model abstained despite chunks clearing the floor: the second
        # layer doing its job. Recorded as a distinct outcome from a
        # floor refusal so `eval` can report which layer caught what.
        return refuse(
            "The model judged the retrieved sources insufficient.",
            before_llm=False,
        )

    text, citations = validate_citations(raw, used)

    return Answer(text=text, citations=citations, refused=False)
