"""Conversation memory: the hybrid context store.

Three layers, each with a distinct job:

  1. `messages`  -- the in-memory list actually sent to the API. This is the
                    ONLY thing the model sees, and the only thing you pay for.
  2. transcript  -- append-only JSONL on disk, never trimmed. Keeps the full
                    record so a benchmark run is reproducible and the cost log
                    is auditable even after layer 1 has been compacted away.
  3. summary     -- (Phase 5) older turns compressed into one block, so history
                    stops growing linearly.

BASELINE BEHAVIOUR (this file, Phase 4): no trimming at all. Full history is
resent every turn. That is deliberately the naive, expensive version -- it is
the number we optimise against, and its O(n^2) cumulative cost is the whole
point of the exercise.

MEMORY CONSTRAINT: the lead will ask the bot about earlier turns to test recall.
So whatever compaction we add in Phase 5 must preserve concrete facts (names,
numbers, decisions, tool results) and compress only conversational filler. A
summary that says "the user introduced themselves" fails that test; one that
says "the user's name is X" passes.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Conversation:
    """Holds chat history and mirrors every message to a transcript file."""

    def __init__(self, system_prompt: str, transcript_path: str | None = None) -> None:
        self._system_prompt = system_prompt
        # The system prompt is stored separately from the turn list so that
        # trimming logic in Phase 5 can never accidentally drop it.
        self.messages: list[dict[str, Any]] = []

        self._transcript_path = Path(transcript_path) if transcript_path else None
        if self._transcript_path:
            self._transcript_path.parent.mkdir(parents=True, exist_ok=True)

    def to_api_messages(self) -> list[dict[str, Any]]:
        """Build the exact payload sent to the API for this turn."""
        return [{"role": "system", "content": self._system_prompt}, *self.messages]

    def append(self, message: dict[str, Any]) -> None:
        """Add a message to live history and mirror it to the transcript."""
        self.messages.append(message)
        self._write_transcript(message)

    def append_all(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            self.append(message)

    def snapshot(self) -> int:
        """Return a marker for the current history length.

        Paired with `rollback`, this lets a failed turn be undone. Without it,
        a turn that dies between appending an assistant tool_call and appending
        the matching tool result leaves history permanently malformed, and
        EVERY later request 400s. See cli.py.
        """
        return len(self.messages)

    def rollback(self, marker: int) -> None:
        """Discard messages added since `marker`.

        Only the in-memory list is truncated. The transcript keeps the partial
        turn on purpose -- it is evidence for debugging what went wrong.
        """
        del self.messages[marker:]

    def _write_transcript(self, message: dict[str, Any]) -> None:
        if not self._transcript_path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": message,
        }
        with self._transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
