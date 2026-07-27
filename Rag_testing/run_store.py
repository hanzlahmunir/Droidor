"""Persist each Run All to disk for later review and comparison.

Two artifacts per run in ``runs/``:
  - ``<timestamp>_<id>.json``  — full structured record (configs + results)
  - ``<timestamp>_<id>.md``    — a readable side-by-side table + answers

This is the durable evidence a testbed needs: what was compared, what each
config answered, and how it performed.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _result_to_dict(result) -> dict:
    return {
        "answer": result.answer,
        "error": result.error,
        "latency_s": result.latency_s,
        "tokens": result.tokens,
        "cost": result.cost,
        "steps": result.steps,
        "sources": [
            {"title": d.metadata.get("title"), **{k: v for k, v in d.metadata.items() if k != "title"}}
            for d in result.sources
        ],
    }


def build_record(run_id: str, query: str, configs, results) -> dict:
    """Assemble the structured record for a run."""
    return {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "windows": [
            {"config": asdict(c), "result": _result_to_dict(r)}
            for c, r in zip(configs, results)
        ],
    }


def _to_markdown(record: dict) -> str:
    lines = [
        f"# Run {record['run_id']} — {record['timestamp']}",
        "",
        f"**Query:** {record['query']}",
        "",
        "## Comparison",
        "",
        "| # | Provider/Model | Effort | Framework | Store | Time | Tokens | Cost | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, w in enumerate(record["windows"], 1):
        c, r = w["config"], w["result"]
        status = "error" if r["error"] else "ok"
        time_s = f"{r['latency_s']:.2f}s" if r["latency_s"] else "-"
        tokens = r["tokens"] if r["tokens"] is not None else "-"
        cost = f"${r['cost']:.4f}" if r["cost"] is not None else "-"
        lines.append(
            f"| {i} | {c['llm_provider']}/{c['llm_model']} | {c['effort']} | "
            f"{c['framework']} | {c['store']} | {time_s} | {tokens} | {cost} | {status} |"
        )

    lines += ["", "## Answers", ""]
    for i, w in enumerate(record["windows"], 1):
        c, r = w["config"], w["result"]
        lines.append(
            f"### Window {i} — {c['framework']}/{c['store']} · "
            f"{c['llm_provider']}:{c['llm_model']} · effort {c['effort']}"
        )
        if r["error"]:
            lines += [f"> ERROR: {r['error']}", ""]
        else:
            if r["steps"]:
                lines += [f"_pipeline: {' > '.join(r['steps'])}_", ""]
            lines += [r["answer"] or "_(empty)_", ""]
    return "\n".join(lines)


def save_run(run_id: str, query: str, configs, results) -> Path:
    """Write JSON + markdown for a run; return the markdown path."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    record = build_record(run_id, query, configs, results)
    stamp = record["timestamp"].replace(":", "-")
    base = RUNS_DIR / f"{stamp}_{run_id}"

    base.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    md_path = base.with_suffix(".md")
    md_path.write_text(_to_markdown(record), encoding="utf-8")
    return md_path


def markdown_for(run_id: str, query: str, configs, results) -> str:
    """Render a run's markdown without writing to disk (for UI download)."""
    return _to_markdown(build_record(run_id, query, configs, results))
