"""FastAPI application: the Documents CRUD API.

Endpoints:
  POST   /documents            create (409 on duplicate url)
  GET    /documents/{id}       fetch one (404 if missing)
  GET    /documents            list, filter by source, paginate
  DELETE /documents/{id}       delete (404 if missing)
"""
from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas import DocumentCreate, DocumentOut

app = FastAPI(title="Documents API")


@app.get("/health")
def health():
    """Liveness probe. docker compose / CI wait on this before running tests."""
    return {"status": "ok"}


@app.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    doc = Document(**payload.model_dump())
    db.add(doc)
    try:
        db.commit()
    except IntegrityError:
        # A duplicate url violates uq_documents_url. We do NOT pre-check with a
        # SELECT: that would leave a race window where two requests both see
        # "not there" and both insert. Instead we let the DB reject the loser
        # and translate its IntegrityError to a clean 409. rollback() clears
        # the failed transaction so this session is usable again.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with this url already exists.",
        )
    # refresh loads DB-generated values (the id) back onto the object.
    db.refresh(doc)
    return doc


@app.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    return doc


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    source: str | None = Query(default=None),
    # limit is bounded (le=100) so a client can't ask for a million rows and
    # OOM the server. offset>=0 keeps the SQL valid.
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Document)
    if source is not None:
        stmt = stmt.where(Document.source == source)
    # Deterministic order is required for pagination to be stable: without
    # ORDER BY, Postgres may return rows in any order and offset/limit would
    # skip or repeat rows between pages. We order by id (insertion order).
    stmt = stmt.order_by(Document.id).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@app.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        # Deleting a missing id is a 404, not a silent success, so the caller
        # knows their assumption (that it existed) was wrong.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    db.delete(doc)
    db.commit()
    # 204 -> no response body.
