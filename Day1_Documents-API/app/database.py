"""Database engine, session factory, and the declarative Base.

Kept separate from models.py and main.py so both can import `Base` and
`get_db` without creating a circular import (models needs Base; main needs
get_db; neither needs the other here).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# A single engine per process holds the connection pool. `pool_pre_ping`
# checks a connection is alive before handing it out, which avoids random
# "server closed the connection" errors after the DB restarts (common in
# docker compose where Postgres may bounce).
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# autocommit/autoflush off is the standard FastAPI pattern: we control the
# transaction boundary explicitly in each request.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a session and always closes it.

    Using a generator with try/finally guarantees the connection returns to
    the pool even if the request handler raises.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
