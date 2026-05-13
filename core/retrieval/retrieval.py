from __future__ import annotations

from typing import Optional

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
        # Fetch a broad slice then filter in Python (sufficient for early scale)
        rows = q.limit(500).all()

        results: list[Entry] = []
        for row in rows:
            d = row.to_dict()
            if tags and not any(t in d["tags"] for t in tags):
                continue
            if query:
                ql = query.lower()
                hit = (
                    ql in d["title"].lower()
                    or ql in d["content"].lower()
                    or any(ql in t.lower() for t in d["tags"])
                )
                if not hit:
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
        neighbor_infos = self._graph.get_neighbors(
            entry_id, relation=relation
        )
        entries: list[Entry] = []
        for info in neighbor_infos:
            entry = self.get_entry_by_id(info["id"])
            if entry:
                entries.append(entry)
        return entries
