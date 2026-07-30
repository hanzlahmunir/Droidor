"""Pydantic schemas: the API's request/response contract.

Separate from the ORM model so the wire format can evolve independently of
the table, and so we never accidentally leak internal columns.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    """Body for POST /documents.

    The four content fields are required and non-empty. published_at is
    optional: a client that knows the article's publish date can supply it,
    and one that doesn't (or couldn't extract it) simply omits it.
    """

    # min_length=1 rejects empty strings at the validation layer -> 422,
    # so an empty title never reaches the DB.
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)
    # Optional with a None default, so every existing client that never heard
    # of this field keeps working unchanged -- adding it is backwards
    # compatible. Pydantic parses ISO-8601 strings into datetime here, so a
    # malformed date is a 422 at the edge rather than bad data in the table.
    published_at: datetime | None = None


class DocumentOut(BaseModel):
    """Response shape for a single document."""

    # from_attributes lets FastAPI build this straight from the ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    text: str
    source: str
    created_at: datetime
    # Always present in the response, but may be null -- the caller can then
    # distinguish "no publish date known" from "field not returned".
    published_at: datetime | None
