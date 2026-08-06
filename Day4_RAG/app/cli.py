"""The command line interface.

    ingest [--reset]     corpus -> chunks -> vectors
    stats                what is currently indexed
    ask "question"       retrieve, then answer with citations
    eval                 measured retrieval quality

ENTRYPOINT, NOT CMD, in compose -- so `run --rm rag ask "question"` appends
arguments rather than replacing the binary. Day 2 lost time to the other
arrangement, where `--mode simple` was parsed as a program name.
"""

from __future__ import annotations

import argparse
import sys

from app.config import Config, ConfigError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag",
        description="Question answering over the Day 3 article corpus.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = sub.add_parser(
        "ingest", help="Load the corpus, chunk it, embed it and store the vectors."
    )
    ingest_cmd.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete the collection first. Required after changing CHUNK_SIZE, "
            "CHUNK_OVERLAP or EMBEDDING_MODEL, because those change what the "
            "stored vectors MEAN and old rows would otherwise linger."
        ),
    )

    sub.add_parser("stats", help="Show what is indexed and under what settings.")

    ask_cmd = sub.add_parser(
        "ask", help="Answer a question from the corpus, with citations."
    )
    ask_cmd.add_argument("question", help="The question to answer.")
    ask_cmd.add_argument(
        "--show-chunks",
        action="store_true",
        help="Print the retrieved chunks and their similarity scores.",
    )
    ask_cmd.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Override TOP_K for this question.",
    )
    ask_cmd.add_argument(
        "--floor",
        type=float,
        default=None,
        help="Override SIMILARITY_FLOOR for this question.",
    )
    ask_cmd.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "Retrieve and show sources without generating an answer. Proves "
            "the retrieval half without spending tokens or needing a key."
        ),
    )

    eval_cmd = sub.add_parser(
        "eval",
        help="Measure retrieval quality and sweep the similarity floor.",
    )
    eval_cmd.add_argument(
        "--floor",
        type=float,
        default=None,
        help="Report failures at this floor (default: the configured value).",
    )
    eval_cmd.add_argument(
        "--report",
        action="store_true",
        help="Write the results to data/reports/EVAL.md as well as printing them.",
    )

    return parser


def cmd_ingest(config: Config, args: argparse.Namespace) -> int:
    from app.embedder import SentenceTransformerEmbedder
    from app.ingest import ingest

    print("Loading the corpus from the Documents API...")
    embedder = SentenceTransformerEmbedder(config)

    report = ingest(config, embedder, reset=args.reset)

    if report.chunks_created == 0:
        # A distinct, diagnosable outcome rather than a silent success. An
        # empty corpus and a broken chunker look identical in a "done" message.
        print(
            "\nNo chunks were produced.\n"
            f"  Articles read: {report.articles_seen}\n"
            "  If that is 0, the corpus is empty -- check that Day 3 has run "
            "and that compose is using day3_crawler_pgdata.\n"
            "  If it is not 0, every article fell below MIN_CHUNK_CHARS."
        )
        return 1

    print()
    print(report.summary())
    print("\nSettings used:")
    for key, value in report.settings.items():
        print(f"  {key:22} {value}")
    return 0


def cmd_stats(config: Config, _args: argparse.Namespace) -> int:
    from collections import Counter

    from app.storage import open_collection

    collection = open_collection(config)
    total = collection.count()

    print(f"Collection : {config.collection_name}")
    print(f"Directory  : {config.chroma_dir}")
    print(f"Chunks     : {total}")

    if total == 0:
        print("\nNothing is indexed yet. Run: ingest")
        return 0

    stored = collection.get(include=["metadatas", "documents"])
    metadatas = stored.get("metadatas") or []
    documents = stored.get("documents") or []

    by_document = Counter(m.get("document_title", "?") for m in metadatas)
    lengths = sorted(len(d) for d in documents)

    print(f"Articles   : {len(by_document)}")
    if lengths:
        mid = lengths[len(lengths) // 2]
        print(
            f"Chunk chars: min {lengths[0]}, median {mid}, max {lengths[-1]}"
        )
    with_heading = sum(1 for m in metadatas if m.get("heading"))
    print(
        f"With heading: {with_heading} "
        f"({100 * with_heading / len(metadatas):.0f}%)"
    )

    print("\nChunks per article:")
    for title, count in by_document.most_common():
        print(f"  {count:4}  {title[:66]}")

    print("\nSettings this collection was built with:")
    for key, value in (collection.metadata or {}).items():
        print(f"  {key:22} {value}")

    return 0


def _print_chunks(chunks, label: str) -> None:
    if not chunks:
        return
    print(f"\n{label}:")
    for index, chunk in enumerate(chunks, start=1):
        heading = f" -- {chunk.heading}" if chunk.heading else ""
        print(f"  [{index}] {chunk.similarity:.3f}  {chunk.document_title[:56]}{heading[:40]}")
        snippet = " ".join(chunk.text.split())[:150]
        print(f"        {snippet}...")


def cmd_ask(config: Config, args: argparse.Namespace) -> int:
    from app.answerer import AnswerError, generate_answer
    from app.embedder import SentenceTransformerEmbedder
    from app.retriever import retrieve

    embedder = SentenceTransformerEmbedder(config)
    result = retrieve(
        args.question,
        config,
        embedder,
        top_k=args.top_k,
        floor=args.floor,
    )

    print(f"\nQ: {args.question}")

    if args.show_chunks or args.no_llm:
        _print_chunks(result.accepted, "Retrieved (above the floor)")
        _print_chunks(result.rejected, "Rejected (below the floor)")

    # THE REFUSAL GATE, before any LLM call. Deterministic, free, and
    # untalkable-around: no tokens are spent on a question the corpus cannot
    # answer.
    if not result.has_evidence:
        from app.answerer import I_DONT_KNOW

        print(f"\nA: {I_DONT_KNOW}")
        print(f"   ({result.explain_refusal()})")
        return 0

    if args.no_llm:
        print(
            f"\n(--no-llm: {len(result.accepted)} chunk(s) cleared the floor; "
            f"no answer generated.)"
        )
        return 0

    try:
        answer = generate_answer(args.question, result.accepted, config)
    except AnswerError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        # Retrieval succeeded even though generation did not, so show what was
        # found rather than leaving the user with nothing.
        if not args.show_chunks:
            _print_chunks(result.accepted, "Retrieved (above the floor)")
        return 1

    print(f"\nA: {answer.text}")

    if answer.refused:
        print(f"   ({answer.reason})")
        return 0

    if answer.cited_sources:
        print("\nSources:")
        for index, source in enumerate(answer.cited_sources, start=1):
            print(f"  [{index}] {source}")
    else:
        # An answer with no valid citation is a red flag worth surfacing: the
        # model either cited nothing or cited something that was not sent.
        print("\n  (No valid citations -- treat this answer with suspicion.)")

    return 0


def cmd_eval(config: Config, args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from pathlib import Path

    from app.embedder import SentenceTransformerEmbedder
    from app.evaluate import describe_failures, evaluate_at, format_sweep, sweep
    from app.storage import open_collection

    collection = open_collection(config)
    if collection.count() == 0:
        print("Nothing is indexed. Run `ingest` first.", file=sys.stderr)
        return 1

    embedder = SentenceTransformerEmbedder(config)
    print("Running retrieval over the evaluation set...")
    points, results = sweep(config, embedder, collection=collection)

    floor = args.floor if args.floor is not None else config.similarity_floor
    at_floor = evaluate_at(floor, results)

    table = format_sweep(points)
    failures = describe_failures(floor, results)

    print(f"\nCorpus: {collection.count()} chunks, top_k={config.top_k}")
    print(
        f"Questions: {at_floor.answerable_total} answerable, "
        f"{at_floor.unanswerable_total} unanswerable\n"
    )
    print("Similarity floor sweep:\n")
    print(table)
    print(f"\nAt the configured floor ({floor:.3f}):")
    print(f"  recall            {at_floor.recall:.1%}")
    print(f"  refusal rate      {at_floor.refusal_rate:.1%}")
    print(f"  false-answer rate {at_floor.false_answer_rate:.1%}")
    print()
    print(failures)

    if args.report:
        path = Path(config.report_dir) / "EVAL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _render_eval_report(config, collection.count(), floor, at_floor, table, failures),
            encoding="utf-8",
        )
        print(f"\nWrote {path}")

    return 0


def _render_eval_report(config, chunk_count, floor, at_floor, table, failures) -> str:
    """The committed evidence for the chosen floor.

    Written to a file rather than only printed because the README quotes these
    numbers, and a number in a README with nothing behind it is the thing Day
    3's report existed to avoid.
    """
    from datetime import datetime, timezone

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    settings = "\n".join(f"| `{k}` | {v} |" for k, v in config.describe().items())

    return f"""# Retrieval Evaluation

Generated: {generated}

Every number here is produced by `rag eval`, over {chunk_count} chunks and the
question set in `data/eval_questions.json`. Re-run it to regenerate.

## What is measured

Two rates, and both are needed. Either one alone is trivially maximised by
breaking the other: a floor of -1 gives perfect recall while answering
everything wrongly, and a floor of 1.0 refuses everything for a perfect
refusal rate. The floor trades one against the other.

- **recall** -- of questions the corpus CAN answer, how often the expected
  article is retrieved.
- **refusal rate** -- of questions it CANNOT answer, how often the similarity
  floor correctly refuses before any LLM call.
- **false-answer rate** -- the complement of refusal: how often it would
  answer something it should not.

This sweep measures RETRIEVAL only. The prompt is a second refusal layer that
catches what the floor lets through; it is not included here because sweeping
a dozen thresholds through an LLM would cost hundreds of calls and make the
numbers depend on sampling.

## The sweep

```
{table}
```

## At the configured floor ({floor:.3f})

| Metric | Value |
| --- | ---: |
| Recall | {at_floor.recall:.1%} |
| Refusal rate | {at_floor.refusal_rate:.1%} |
| False-answer rate | {at_floor.false_answer_rate:.1%} |
| Answerable questions | {at_floor.answerable_total} |
| Unanswerable questions | {at_floor.unanswerable_total} |

## What it gets wrong

```
{failures}
```

## Settings these numbers were measured under

| Setting | Value |
| --- | --- |
{settings}
"""


COMMANDS = {
    "ingest": cmd_ingest,
    "stats": cmd_stats,
    "ask": cmd_ask,
    "eval": cmd_eval,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = Config()
    except ConfigError as exc:
        # A config mistake is the user's to fix, so it gets a plain message
        # rather than a traceback pointing into our validation code.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    handler = COMMANDS[args.command]
    try:
        return handler(config, args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Deliberately not a bare traceback: these are the errors a user can
        # act on -- an unreachable API, a mismatched model, a collection that
        # needs rebuilding -- and each one already carries its own remedy.
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
