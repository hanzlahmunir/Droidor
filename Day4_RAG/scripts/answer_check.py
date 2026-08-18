"""Run the answerable eval questions END TO END and check the citations.

WHY THIS EXISTS SEPARATELY FROM `rag eval`.

`eval` measures RETRIEVAL: does the right article come back, and does the
floor let it through. It deliberately does not call the LLM, because sweeping
a dozen thresholds through a model would cost hundreds of calls and make the
numbers depend on sampling.

But retrieval finding the right chunk does not mean the ANSWER is right. At
112 articles the model is handed 12 chunks that can include near-duplicates --
two adjacent sqlite-utils releases, three Django posts -- and picking the
right one among them is a property of the model, not the retriever. On the
sqlite-utils question the WRONG release ranks first at 0.845 while the
answer-bearing chunk sits at rank 4.

So this asks each question for real, and checks that the expected article is
among the sources actually cited. It is a separate script rather than part of
`eval` because it costs one LLM call per question and should be an explicit
act.

    python scripts/answer_check.py            # all answerable questions
    python scripts/answer_check.py --limit 5  # a quick subset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.answerer import AnswerError, generate_answer  # noqa: E402
from app.config import Config  # noqa: E402
from app.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.evaluate import load_questions  # noqa: E402
from app.retriever import retrieve  # noqa: E402
from app.storage import open_collection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    config = Config()
    collection = open_collection(config)
    embedder = SentenceTransformerEmbedder(config)

    answerable, _ = load_questions(config)
    if args.limit:
        answerable = answerable[: args.limit]

    print(f"Asking {len(answerable)} answerable questions end to end.")
    print(f"Corpus: {collection.count()} chunks, top_k={config.top_k}, "
          f"floor={config.similarity_floor}\n")

    results = []
    cited_ok = refused = no_citation = errored = 0

    for index, item in enumerate(answerable, start=1):
        question = item["question"]
        expected = item.get("expect_sources", [])

        result = retrieve(question, config, embedder, collection=collection)

        row: dict[str, object] = {
            "question": question,
            "expected": expected[0] if expected else "",
            "best_similarity": result.best_similarity,
        }

        if not result.has_evidence:
            refused += 1
            row["outcome"] = "REFUSED_BY_FLOOR"
            row["answer"] = ""
            print(f"[{index:2}] REFUSED (floor)  {question[:62]}")
        else:
            try:
                answer = generate_answer(question, result.accepted, config)
            except AnswerError as exc:
                errored += 1
                row["outcome"] = "ERROR"
                row["answer"] = str(exc)
                print(f"[{index:2}] ERROR            {question[:62]}")
            else:
                sources = answer.cited_sources
                row["answer"] = answer.text
                row["cited"] = sources

                if answer.refused:
                    refused += 1
                    row["outcome"] = "REFUSED_BY_MODEL"
                    print(f"[{index:2}] REFUSED (model)  {question[:62]}")
                elif not sources:
                    no_citation += 1
                    row["outcome"] = "NO_CITATION"
                    print(f"[{index:2}] NO CITATION      {question[:62]}")
                elif any(e in s for e in expected for s in sources):
                    cited_ok += 1
                    row["outcome"] = "CITED_EXPECTED"
                    print(f"[{index:2}] ok               {question[:62]}")
                else:
                    row["outcome"] = "CITED_WRONG"
                    print(f"[{index:2}] WRONG SOURCE     {question[:62]}")
                    print(f"     expected: {expected[0][:66] if expected else '?'}")
                    print(f"     cited:    {sources[0][:66]}")

        results.append(row)

    total = len(answerable)
    wrong = total - cited_ok - refused - no_citation - errored

    print(f"\n{'='*66}")
    print(f"  cited the expected article : {cited_ok}/{total}")
    print(f"  cited a DIFFERENT article  : {wrong}")
    print(f"  refused                    : {refused}")
    print(f"  answered with no citation  : {no_citation}")
    print(f"  errored                    : {errored}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
