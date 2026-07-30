"""Shared fixtures.

The whole suite is OFFLINE: no network, no database, no API keys. That is a
deliberate constraint, for two reasons:

  1. CI must not depend on five external blogs being up. A test that fails
     because jvns.ca is having a bad afternoon teaches nothing and trains
     people to ignore red builds.
  2. A crawler's unit tests should exercise the crawler's LOGIC -- URL
     repair, date parsing, junk rules, dedupe -- against fixed inputs. Those
     are exactly the parts that must be deterministic.

Live behaviour is verified separately, by actually running the crawl and
checking the report, which is recorded in the commit message.
"""

import os

import pytest

# Config reads DATABASE_URL with no default and raises KeyError if it is
# missing. Set before any app import. Nothing in the offline suite opens a
# connection, so the value only has to be present, not reachable.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:5432/unused"
)

from app.config import Config  # noqa: E402


@pytest.fixture
def config() -> Config:
    """A Config with the documented defaults."""
    return Config()
