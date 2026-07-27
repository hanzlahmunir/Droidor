"""Application configuration, loaded from environment variables.

We read config from the environment (not hardcoded) so the same image runs
against the dev DB, the test DB, and CI's Postgres just by changing env vars.
Docker Compose injects DATABASE_URL; pytest overrides it with TEST_DATABASE_URL.
"""
import os


class Settings:
    # SQLAlchemy connection string, e.g.
    #   postgresql+psycopg://user:pass@host:5432/dbname
    # No default on purpose: if it's missing we want a loud failure at startup,
    # not a silent fallback to some wrong/local DB.
    DATABASE_URL: str = os.environ["DATABASE_URL"]


settings = Settings()
