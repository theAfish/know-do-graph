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

        # Split query into tokens so multi-word phrases match entries containing
        # *any* individual token (broad OR), then rank by token hit count.
        _STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "be"}
        tokens: list[str] = []
        if query:
            tokens = [
                t for t in query.lower().split()
                if len(t) > 2 and t not in _STOP_WORDS
            ]
            if not tokens:
                tokens = [query.lower()]

            token_filters = []
            for token in tokens:
                tl = f"%{token}%"
                token_filters.append(
                    or_(
                        EntryModel.title.ilike(tl),
                        EntryModel.content.ilike(tl),
                        EntryModel.aliases.ilike(tl),
                    )
                )
            q = q.filter(or_(*token_filters))

        rows = q.limit(500).all()

        scored: list[tuple[int, Entry]] = []
        for row in rows:
            d = row.to_dict()
            if tags and not any(t in d["tags"] for t in tags):
                continue
            entry = Entry(**d)
            if tokens:
                title = (d.get("title") or "").lower()
                aliases = str(d.get("aliases") or "").lower()
                tags_str = str(d.get("tags") or "").lower()
                content = (d.get("content") or "").lower()
                score = 0
                for token in tokens:
                    if token in title:
                        score += 10
                    if token in aliases:
                        score += 5
                    if token in tags_str:
                        score += 3
                    if token in content and token not in title:
                        score += 1
            else:
                score = 0
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

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

