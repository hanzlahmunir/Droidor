"""Pydantic schemas: the API's request/response contract.

Separate from the ORM model so the wire format can evolve independently of
the table, and so we never accidentally leak internal columns.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    """Body for POST /documents. All four fields required and non-empty."""

    # min_length=1 rejects empty strings at the validation layer -> 422,
    # so an empty title never reaches the DB.
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)


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
