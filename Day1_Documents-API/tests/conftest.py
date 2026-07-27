"""Pytest fixtures.

Design decisions:
- We test against a REAL Postgres (TEST_DATABASE_URL), never SQLite. SQLite
  would let bugs through: it doesn't enforce VARCHAR length, its unique/enum
  behavior differs, and the whole point of Day 1 is Postgres semantics (409 on
  a real unique index).
- Schema is built by running the Alembic MIGRATION (upgrade head), not
  create_all. This means the tests also prove the migration works.
- Each test gets a clean table via TRUNCATE, so tests are independent and
  order doesn't matter.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

# The app reads DATABASE_URL at import time (config.py). Point it at the test
# DB BEFORE importing anything from app.*, so the engine binds to the test DB.
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Run migrations once per test session: downgrade to base then up to head.

    Downgrade-first guarantees a clean slate even if a previous run left the
    DB in some state, and it exercises the downgrade path too.
    """
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_table():
    """Empty the documents table before each test so tests don't leak into
    each other. RESTART IDENTITY resets the id sequence for predictable ids."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE documents RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    """A FastAPI test client that talks to the real app over ASGI."""
    return TestClient(app)


@pytest.fixture
def sample_payload():
    return {
        "title": "Intro to RAG",
        "url": "https://example.com/rag",
        "text": "Retrieval augmented generation basics.",
        "source": "blog",
    }
