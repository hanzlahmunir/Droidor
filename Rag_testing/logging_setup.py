"""Central logging configuration for the backend.

Everything the pipeline does — routing decisions, generated queries, retrieval
counts, per-config timing, errors — goes through a single logger so there is one
durable, greppable record in ``logs/backend.log`` (rotating) plus console output.

Call ``get_logger(__name__)`` from any module; ``setup_logging`` is idempotent
and runs once on first import.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "backend.log"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root 'rag' logger once (console + rotating file)."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("rag")
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a child of the 'rag' logger, configuring logging on first use."""
    setup_logging()
    # Namespace under 'rag' so all our modules share one config.
    short = name.split(".")[-1]
    return logging.getLogger(f"rag.{short}")
