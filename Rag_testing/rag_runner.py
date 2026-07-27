"""Orchestrator: turn a RagConfig into a pipeline, run it, attach metrics.

``run_one`` builds the store/llm/framework from a config and executes it,
capturing latency and token/cost usage, and never raising — a failing config
returns a RagResult with ``error`` set so it can't take down a comparison.
``run_all`` fans a single query out to every config concurrently (thread pool,
since the framework calls are synchronous) and returns results in input order.

Every run is logged (see logging_setup) and persisted to ``runs/`` for later
review (see run_store).
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from config import RagConfig, settings_from_config
from frameworks.base import RagResult, get_framework
from llms.registry import get_llm
from logging_setup import get_logger
from metrics import new_usage_callback, summarize_usage, timer
from run_store import save_run
from stores.base import get_store

log = get_logger(__name__)


def run_one(config: RagConfig, query: str, run_id: str = "-") -> RagResult:
    """Run a single pipeline for ``config`` over ``query``. Never raises."""
    tag = f"[{run_id}] {config.framework}/{config.store}/{config.llm_provider}:{config.llm_model} e={config.effort}"
    log.info("%s START query=%r", tag, query)
    try:
        settings = settings_from_config(config)
        store = get_store(config.store)
        llm = get_llm(config.llm_provider, config.llm_model, settings.reasoning_effort)
        framework = get_framework(config.framework)

        usage_cb = new_usage_callback()
        # Bind the usage callback so every LLM call in the pipeline is counted.
        llm_with_usage = llm.with_config({"callbacks": [usage_cb]})

        with timer() as elapsed:
            result = framework.run(query, store, llm_with_usage, settings)
        result.latency_s = round(elapsed(), 3)

        tokens, cost = summarize_usage(usage_cb, config.llm_model)
        result.tokens = tokens
        result.cost = cost

        log.info(
            "%s DONE latency=%.3fs tokens=%s cost=%s steps=%s",
            tag, result.latency_s, tokens, cost, " > ".join(result.steps),
        )
        log.info("%s ANSWER: %s", tag, (result.answer or "")[:500].replace("\n", " "))
        return result

    except Exception as exc:  # isolate failures per-config
        log.exception("%s ERROR: %s", tag, exc)
        return RagResult(answer="", error=f"{type(exc).__name__}: {exc}")


def run_all(configs: list[RagConfig], query: str) -> list[RagResult]:
    """Run every config concurrently; results in input order. Logged + persisted."""
    if not configs:
        return []
    run_id = uuid.uuid4().hex[:8]
    log.info("===== RUN %s: %d config(s) | query=%r =====", run_id, len(configs), query)

    with ThreadPoolExecutor(max_workers=min(8, len(configs))) as pool:
        results = list(pool.map(lambda c: run_one(c, query, run_id), configs))

    ok = sum(1 for r in results if not r.error)
    log.info("===== RUN %s COMPLETE: %d/%d succeeded =====", run_id, ok, len(results))

    try:
        path = save_run(run_id, query, configs, results)
        log.info("[%s] saved run -> %s", run_id, path)
    except Exception as exc:  # persistence must never break a run
        log.warning("[%s] could not save run: %s", run_id, exc)

    return results
