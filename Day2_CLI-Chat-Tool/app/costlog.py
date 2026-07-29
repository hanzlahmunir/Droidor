"""Per-call cost logging to a file.

The brief requires the cost log to be WRITTEN TO A FILE, not just printed, so
the numbers survive the session and can be aggregated afterwards.

Format is JSONL (one JSON object per line) rather than CSV because:
  - it appends safely without rewriting the file,
  - a partial write at the end corrupts one line, not the whole file,
  - the benchmark script can parse it without a schema.

One record per API CALL, not per user turn. A single turn that uses two tools
makes three calls, and attributing cost to the turn requires seeing all three.
`turn_index` ties them together.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.pricing import TurnCost, is_known_model


@dataclass
class SessionTotals:
    """Running totals for the whole session."""

    calls: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    per_model_calls: dict[str, int] = field(default_factory=dict)

    @property
    def cost_per_turn_usd(self) -> float:
        """The headline number for the before/after comparison."""
        return self.cost_usd / self.turns if self.turns else 0.0


class CostLogger:
    """Appends per-call cost records and tracks session totals."""

    def __init__(self, path: str, config_label: str = "baseline") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Distinguishes runs in the log, so baseline and optimised records can
        # live in one file and still be told apart by the benchmark.
        self.config_label = config_label

        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.totals = SessionTotals()

    def record(self, cost: TurnCost, turn_index: int, call_index: int) -> None:
        """Write one API call's cost and update session totals."""
        self.totals.calls += 1
        self.totals.input_tokens += cost.input_tokens
        self.totals.output_tokens += cost.output_tokens
        self.totals.cost_usd += cost.total_cost_usd
        self.totals.per_model_calls[cost.model] = (
            self.totals.per_model_calls.get(cost.model, 0) + 1
        )

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "config": self.config_label,
            "turn_index": turn_index,
            "call_index": call_index,
            **asdict(cost),
            "total_cost_usd": cost.total_cost_usd,
            # Flags that this row used the fallback rate, so an unknown model
            # cannot quietly distort the headline average.
            "estimated_rate": not is_known_model(cost.model),
        }
        self._append(record)

    def mark_turn_complete(self) -> None:
        """Count a completed user turn (may span several API calls)."""
        self.totals.turns += 1

    def write_session_summary(self) -> dict:
        """Append a summary record and return it for display."""
        summary = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "config": self.config_label,
            "type": "session_summary",
            "turns": self.totals.turns,
            "api_calls": self.totals.calls,
            "input_tokens": self.totals.input_tokens,
            "output_tokens": self.totals.output_tokens,
            "total_cost_usd": self.totals.cost_usd,
            "cost_per_turn_usd": self.totals.cost_per_turn_usd,
            "per_model_calls": self.totals.per_model_calls,
        }
        self._append(summary)
        return summary

    def _append(self, record: dict) -> None:
        # Logging must never take down the chat, so a failure here is reported
        # and swallowed rather than raised.
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"[cost log] warning: could not write to {self.path}: {exc}")
