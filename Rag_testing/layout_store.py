"""Persist the UI window layout across refreshes.

Streamlit clears ``session_state`` on browser refresh, so the windows a user set
up would vanish. We save just the window *configs* (provider/model/effort/
framework/store) to a small JSON file and reload them on startup. Results are not
persisted here — those live in ``runs/`` already.
"""
from __future__ import annotations

import json
from pathlib import Path

LAYOUT_FILE = Path(__file__).resolve().parent / ".layout.json"

_KEYS = (
    "provider", "model", "effort", "framework", "store",
    "k", "rewrite_query", "grade_docs", "reasoning_effort",
)


def save_layout(windows: list[dict]) -> None:
    """Write the current window configs to disk (best-effort)."""
    try:
        clean = [{k: w.get(k) for k in _KEYS} for w in windows]
        LAYOUT_FILE.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    except Exception:
        pass  # persistence must never break the UI


def load_layout() -> list[dict] | None:
    """Return saved window configs, or None if there's no valid saved layout."""
    if not LAYOUT_FILE.exists():
        return None
    try:
        data = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return [{k: w.get(k) for k in _KEYS} for w in data]
    except Exception:
        return None
    return None
