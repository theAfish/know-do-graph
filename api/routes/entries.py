from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.app_state import graph as _graph
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import EdgeRelation
from core.schemas.entry import Entry, EntryType
from core.storage.database import get_db
from core.storage.repository import EdgeRepository, EntryRepository

router = APIRouter()


def _engine(db: Session = Depends(get_db)) -> RetrievalEngine:
    return RetrievalEngine(db, _graph)


@router.get("/", response_model=list[dict])
def list_entries(
    limit: int = 20,
    offset: int = 0,
    engine: RetrievalEngine = Depends(_engine),
):
    """List entries with pagination."""
    return [e.model_dump(mode="json") for e in engine.list_entries(limit=limit, offset=offset)]


@router.get("/search", response_model=list[dict])
def search_entries(
    q: Optional[str] = None,
    tags: Optional[str] = None,
    entry_type: Optional[EntryType] = None,
    limit: int = 20,
    engine: RetrievalEngine = Depends(_engine),
):
    """Full-text search with optional tag and type filters.

    `tags` is a comma-separated string, e.g. `tags=atomistic,python`.
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = engine.search_entries(query=q, tags=tag_list, entry_type=entry_type, limit=limit)
    return [e.model_dump(mode="json") for e in results]


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """Retrieve a single entry by ID or slug."""
    entry = engine.get_entry_by_id(entry_id) or engine.get_entry_by_slug(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry.model_dump(mode="json")


@router.post("/", response_model=dict, status_code=201)
def create_entry(entry: Entry, db: Session = Depends(get_db)):
    """Create a new entry."""
    saved = EntryRepository(db).create(entry)
    _graph.add_entry(saved)
    return saved.model_dump(mode="json")


@router.put("/{entry_id}", response_model=dict)
def update_entry(entry_id: str, entry: Entry, db: Session = Depends(get_db)):
    """Update an existing entry."""
    entry.id = entry_id
    updated = EntryRepository(db).update(entry)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    _graph.add_entry(updated)
    return updated.model_dump(mode="json")


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    """Delete an entry and its node from the in-memory graph."""
    if not EntryRepository(db).delete(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    _graph.remove_entry(entry_id)


@router.get("/{entry_id}/related", response_model=list[dict])
def get_related(
    entry_id: str,
    depth: int = 1,
    relation: Optional[EdgeRelation] = None,
    engine: RetrievalEngine = Depends(_engine),
):
    """Return entries related to *entry_id* via the graph."""
    related = engine.get_related_entries(entry_id, depth=depth, relation=relation)
    return [e.model_dump(mode="json") for e in related]


@router.get("/{entry_id}/edges", response_model=list[dict])
def get_edges(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """Return all edges incident to *entry_id*."""
    return [e.model_dump(mode="json") for e in engine.get_edges_for_entry(entry_id)]
