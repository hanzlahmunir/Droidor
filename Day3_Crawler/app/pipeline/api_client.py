"""Client for the Day 1 Documents API.

WHY HTTP AND NOT DIRECT DATABASE WRITES.
The crawler could import Day 1's SQLAlchemy model and INSERT straight into
the documents table -- same Postgres, fewer moving parts. It deliberately
does not, for three reasons:

  1. The task says "push them into your Day 1 API". Going around the API
     would technically populate the table while leaving the thing being
     tested unexercised.
  2. Writing directly bypasses the API's contract: the 409-on-duplicate-url
     path, the 422 validation, the published_at parsing. Those are Day 1's
     guarantees, and the only way to know they hold under real crawler
     output is to actually send real crawler output through them.
  3. Two writers to one table means two places enforcing invariants, which
     is how they drift apart.

The cost is a network hop per document, which is irrelevant next to the
seconds already spent politely waiting between fetches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import Config


@dataclass(frozen=True)
class PushResult:
    """Outcome of one POST /documents."""

    ok: bool
    document_id: int | None = None
    http_status: int | None = None
    duplicate: bool = False
    """True when the API returned 409 -- the url already exists. Not an
    error: it is the API's unique constraint working, and the crawler's own
    URL layer should normally have caught it first."""
    error: str | None = None


class DocumentsAPIClient:
    """Thin client for the endpoints the crawler needs."""

    def __init__(self, config: Config, client: httpx.Client | None = None) -> None:
        self._config = config
        self._base = config.api_base_url
        # A SEPARATE httpx client from the crawler's. The crawl client sends
        # a crawler User-Agent, uses HTTP/2 and follows redirects -- none of
        # which is right for talking to our own internal API, and mixing them
        # would send our crawler UA to Day 1 in every request.
        self._client = client or httpx.Client(timeout=30.0)

    def health(self) -> bool:
        """Is the API up? Used by the entrypoint before a run starts."""
        try:
            response = self._client.get(f"{self._base}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def create_document(
        self,
        *,
        title: str,
        url: str,
        text: str,
        source: str,
        published_at: datetime | None,
    ) -> PushResult:
        """POST one document. Never raises; returns a PushResult.

        Field limits are enforced here, matching Day 1's schema, so a long
        title is truncated to something storable rather than bouncing off the
        API as a 422. Day 1 declares title max_length=500 and source
        max_length=200; exceeding either is a validation error there.
        """
        payload = {
            # Truncated rather than rejected: a 600-character title is a real
            # article with a long headline, and losing the document over the
            # last 100 characters of its title would be the wrong trade.
            "title": (title or "Untitled")[:500],
            "url": url[:2000],
            "text": text,
            "source": source[:200],
        }

        # Only send published_at when we have one. Omitting the key entirely
        # is what an older client would do, and Day 1 treats that as null --
        # exercising the backwards-compatible path rather than sending an
        # explicit null every time.
        if published_at is not None:
            # isoformat() on an aware datetime yields "+00:00", which
            # Pydantic parses. Sending a naive datetime here would make the
            # API guess a timezone.
            payload["published_at"] = published_at.isoformat()

        try:
            response = self._client.post(f"{self._base}/documents", json=payload)
        except httpx.HTTPError as exc:
            return PushResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        if response.status_code == 201:
            body = response.json()
            return PushResult(ok=True, document_id=body.get("id"), http_status=201)

        if response.status_code == 409:
            # The API's unique constraint fired. Expected and handled, not an
            # error: it means this URL is already stored. Reaching here also
            # tells us our own URL dedupe missed something, which is worth
            # seeing in the report rather than swallowing.
            return PushResult(ok=False, http_status=409, duplicate=True)

        # Anything else (422 in practice) means the crawler produced a payload
        # the API refused. Surfaced with the API's own message rather than a
        # generic failure, because it indicates a bug on our side.
        detail = ""
        try:
            detail = str(response.json())[:300]
        except ValueError:
            detail = response.text[:300]

        return PushResult(
            ok=False,
            http_status=response.status_code,
            error=f"HTTP {response.status_code}: {detail}",
        )

    def list_documents(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Read documents back. Used by the UI's browse tab and by verification.

        Reading through the API rather than the database is the same argument
        as writing through it: the UI shows what a real consumer of the API
        would see, so "here are 3 stored articles, they are clean" is a
        demonstration of the actual system.
        """
        try:
            response = self._client.get(
                f"{self._base}/documents", params={"limit": limit, "offset": offset}
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return []

    def get_document(self, document_id: int) -> dict | None:
        try:
            response = self._client.get(f"{self._base}/documents/{document_id}")
            if response.status_code == 200:
                return response.json()
        except (httpx.HTTPError, ValueError):
            pass
        return None
