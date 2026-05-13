from __future__ import annotations

from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryType
from core.storage.models import EdgeModel, EntryModel


class RetrievalEngine:
    """Search and graph-traversal interface over the persisted graph."""

    def __init__(self, db: Session, graph: KnowDoGraph) -> None:
        self._db = db
        self._graph = graph

    # ------------------------------------------------------------------
    # Entry lookups
    # ------------------------------------------------------------------

    def get_entry_by_id(self, entry_id: str) -> Optional[Entry]:
        row = self._db.get(EntryModel, entry_id)
        return Entry(**row.to_dict()) if row else None

    def get_entry_by_slug(self, slug: str) -> Optional[Entry]:
        row = self._db.query(EntryModel).filter_by(slug=slug).first()
        return Entry(**row.to_dict()) if row else None

    def get_entry_by_alias(self, alias: str) -> Optional[Entry]:
        """Return the first entry whose aliases list contains *alias* (case-insensitive)."""
        alias_lower = alias.lower()
        # Aliases are stored as a JSON array in a Text column; use LIKE for a quick scan.
        rows = (
            self._db.query(EntryModel)
            .filter(EntryModel.aliases.ilike(f"%{alias_lower}%"))
            .all()
        )
        for row in rows:
            entry = Entry(**row.to_dict())
            if any(a.lower() == alias_lower for a in entry.aliases):
                return entry
        return None

    def resolve_identifier(self, identifier: str) -> Optional[Entry]:
        """Try ID → slug → alias in order and return the first match."""
        return (
            self.get_entry_by_id(identifier)
            or self.get_entry_by_slug(identifier)
            or self.get_entry_by_alias(identifier)
        )

    def list_entries(self, limit: int = 50, offset: int = 0) -> list[Entry]:
        rows = self._db.query(EntryModel).offset(offset).limit(limit).all()
        return [Entry(**row.to_dict()) for row in rows]

    def search_entries(
        self,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        entry_type: Optional[EntryType] = None,
        limit: int = 20,
    ) -> list[Entry]:
        q = self._db.query(EntryModel)
        if entry_type:
            q = q.filter(EntryModel.entry_type == entry_type.value)
        # Push title/content/alias matching down to SQL before pulling rows
        if query:
            ql = f"%{query}%"
            q = q.filter(
                or_(
                    EntryModel.title.ilike(ql),
                    EntryModel.content.ilike(ql),
                    EntryModel.aliases.ilike(ql),
                )
            )
        rows = q.limit(500).all()

        results: list[Entry] = []
        for row in rows:
            d = row.to_dict()
            # Tags are JSON-serialised; filter in Python
            if tags and not any(t in d["tags"] for t in tags):
                continue
            results.append(Entry(**d))
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------------
    # Edge lookups
    # ------------------------------------------------------------------

    def get_edges_for_entry(self, entry_id: str) -> list[Edge]:
        rows = (
            self._db.query(EdgeModel)
            .filter(
                (EdgeModel.source_id == entry_id)
                | (EdgeModel.target_id == entry_id)
            )
            .all()
        )
        return [Edge(**row.to_dict()) for row in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_related_entries(
        self,
        entry_id: str,
        depth: int = 1,
        relation: Optional[EdgeRelation] = None,
    ) -> list[Entry]:
        related_ids = self._graph.get_related_ids(entry_id, depth=depth, relation=relation)
        entries: list[Entry] = []
        for rid in related_ids:
            entry = self.get_entry_by_id(rid)
            if entry:
                entries.append(entry)
        return entries

