"""SQLAlchemy ORM models.

Note: this model is the *application's* view of the table. The table is
actually created by the Alembic migration, NOT by Base.metadata.create_all.
Keeping them in sync is our job; CI catches drift because tests run the
migration and then use this model against it.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    # A DB-side unique constraint on url. This is what makes the "duplicate
    # POST returns 409" rule *correct under concurrency*: the database, not
    # our Python code, is the single arbiter of uniqueness. Two racing inserts
    # can both pass an app-level "does it exist?" check, but only one can win
    # the unique index; the other gets an IntegrityError we translate to 409.
    __table_args__ = (UniqueConstraint("url", name="uq_documents_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # default is set in Python (not server_default) so it's identical in
        # SQLite-free test runs and Postgres alike, and easy to reason about.
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
