"""Engine and session factory for the crawler's own database.

Mirrors Day 1's database.py so there is one set of DB conventions in the
repo, with one difference: this module exposes a context manager rather than
a FastAPI dependency, because the crawler is a script and a Streamlit app,
not a web framework.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.storage.models import Base

_config = Config()

# pool_pre_ping tests a pooled connection before handing it out. Without it,
# a connection that Postgres closed while the crawler was sleeping between
# polite per-host delays comes back as a stale-connection error on the next
# query. A crawler idles by design, so this is not optional here.
engine = create_engine(
    _config.database_url,
    pool_pre_ping=True,
    # Modest pool: this is a single-process crawler plus a Streamlit UI, not
    # a web server. A large pool would just hold idle Postgres connections.
    pool_size=5,
    max_overflow=5,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception.

    expire_on_commit=False above means objects stay usable after the session
    closes, so a caller can read attributes off a returned record without
    triggering a lazy refresh against a dead session.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_schema() -> None:
    """Create the crawler's tables if they do not exist.

    WHY create_all HERE, when Day 1 insists on migrations.

    Day 1's rule exists because `documents` is a published contract: other
    things read it, its schema evolves, and a downgrade must be reviewable.
    These two tables are internal, disposable bookkeeping -- a scratchpad the
    crawler rebuilds. There is no consumer to break and nothing to migrate:
    if the schema changes, the correct action is to drop and re-crawl.

    Adding an Alembic setup here would be ceremony that implies a stability
    guarantee this data does not have. The `documents` table it writes to is
    still migration-managed, in Day 1, where the rule belongs.
    """
    Base.metadata.create_all(bind=engine)
