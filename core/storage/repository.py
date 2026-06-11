from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from core.schemas.edge import Edge
from core.schemas.entry import Entry

logger = logging.getLogger(__name__)


def _notify(event_type: str, data: dict) -> None:
    """Best-effort SSE broadcast on graph mutations.

    Safe to call from CLI processes (no event loop → silently no-ops) and from
    API worker threads. Never raises.
    """
    try:
        from core import events as _events
        _events.emit(event_type, data)
    except Exception:
        pass


def _unique_slug(db: Session, base_slug: str, entry_id: str) -> str:
    from core.storage.models import EntryModel

    def _taken(s: str) -> bool:
        return (
            db.query(EntryModel)
            .filter(EntryModel.slug == s, EntryModel.id != entry_id)
            .first()
            is not None
        )

    if not _taken(base_slug):
        return base_slug
    for i in range(1, 1000):
        candidate = f"{base_slug}-{i}"
        if not _taken(candidate):
            return candidate
    return f"{base_slug}-{entry_id[:8]}"


def _refresh_embedding(db: Session, entry: Entry, model) -> None:
    """Compute / refresh the embedding row for *entry* and stamp its hash.

    Failures are logged and swallowed — embedding must never break writes.
    """
    from core.retrieval import vector_store
    from core.retrieval.embedder import build_embedding_text, get_default_embedder, text_hash

    try:
        embedder = get_default_embedder()
        if not embedder.available:
            return
        text = build_embedding_text(
            title=entry.title,
            aliases=entry.aliases,
            tags=entry.tags,
            content=entry.content,
        )
        new_hash = text_hash(text)
        if model.embedding_hash == new_hash:
            return
        vec = embedder.embed([text])[0]
        if not vec:
            return
        if vector_store.upsert(db, entry.id, vec):
            model.embedding_hash = new_hash
            db.commit()
    except Exception as exc:
        logger.warning("embedding refresh failed for %s: %s", entry.id, exc)
        try:
            db.rollback()
        except Exception:
            pass


class EntryRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, entry: Entry) -> Entry:
        from core.storage.models import EntryModel

        # A newly-created node always starts with no review history.
        entry.metadata.review_count = 0
        entry.metadata.modify_count = 0
        entry.metadata.last_reviewed_at = None
        slug = _unique_slug(self._db, entry.slug or _slug(entry.title), entry.id)
        model = EntryModel(
            id=entry.id,
            title=entry.title,
            slug=slug,
            entry_type=entry.entry_type.value,
            content=entry.content,
            tags=json.dumps(entry.tags),
            aliases=json.dumps(entry.aliases),
            metadata_json=json.dumps(entry.metadata.model_dump(mode="json")),
            internal_refs=json.dumps(entry.internal_refs),
            scripts_json=json.dumps([s.model_dump() for s in entry.scripts]),
            assets_json=json.dumps([a.model_dump() for a in entry.assets]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        saved = Entry(**model.to_dict())
        _refresh_embedding(self._db, saved, model)
        _notify("node_added", {"id": saved.id, "title": saved.title, "slug": saved.slug})
        return saved

    def update(self, entry: Entry) -> Optional[Entry]:
        from core.storage.models import EntryModel

        model = self._db.get(EntryModel, entry.id)
        if not model:
            return None
        model.title = entry.title
        model.slug = _unique_slug(self._db, entry.slug or _slug(entry.title), entry.id)
        model.entry_type = entry.entry_type.value
        model.content = entry.content
        model.tags = json.dumps(entry.tags)
        model.aliases = json.dumps(entry.aliases)
        model.metadata_json = json.dumps(entry.metadata.model_dump(mode="json"))
        model.internal_refs = json.dumps(entry.internal_refs)
        model.scripts_json = json.dumps([s.model_dump() for s in entry.scripts])
        model.assets_json = json.dumps([a.model_dump() for a in entry.assets])
        model.updated_at = datetime.utcnow()
        self._db.commit()
        self._db.refresh(model)
        saved = Entry(**model.to_dict())
        _refresh_embedding(self._db, saved, model)
        _notify("node_updated", {"id": saved.id, "title": saved.title, "slug": saved.slug})
        return saved

    def delete(self, entry_id: str) -> bool:
        from core.retrieval import vector_store
        from core.storage.models import EdgeModel, EntryModel

        model = self._db.get(EntryModel, entry_id)
        if not model:
            return False
        incident_edges = (
            self._db.query(EdgeModel)
            .filter(
                (EdgeModel.source_id == entry_id)
                | (EdgeModel.target_id == entry_id)
            )
            .all()
        )
        removed_edges = [
            {
                "id": edge.id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
            }
            for edge in incident_edges
        ]
        for edge in incident_edges:
            self._db.delete(edge)
        self._db.delete(model)
        self._db.commit()
        vector_store.delete(self._db, entry_id)
        for edge in removed_edges:
            _notify("edge_removed", edge)
        _notify("node_removed", {"id": entry_id})
        return True

    def get_all(self) -> list[Entry]:
        from core.storage.models import EntryModel

        rows = self._db.query(EntryModel).all()
        return [Entry(**row.to_dict()) for row in rows]


class EdgeRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, edge: Edge) -> Edge:
        from core.storage.models import EdgeModel

        # Skip duplicates (same source/target/relation)
        existing = (
            self._db.query(EdgeModel)
            .filter_by(source_id=edge.source_id, target_id=edge.target_id, relation=edge.relation.value)
            .first()
        )
        if existing:
            return Edge(**existing.to_dict())

        model = EdgeModel(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation.value,
            weight=edge.weight,
            metadata_json=json.dumps(edge.metadata),
            created_at=datetime.utcnow(),
        )
        self._db.add(model)
        self._db.commit()
        _notify("edge_added", {
            "id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "relation": edge.relation.value,
        })
        return edge

    def delete(self, edge_id: str) -> bool:
        from core.storage.models import EdgeModel

        model = self._db.get(EdgeModel, edge_id)
        if not model:
            return False
        src, tgt, rel = model.source_id, model.target_id, model.relation
        self._db.delete(model)
        self._db.commit()
        _notify("edge_removed", {"id": edge_id, "source_id": src, "target_id": tgt, "relation": rel})
        return True

    def get_all(self) -> list[Edge]:
        from core.storage.models import EdgeModel

        rows = self._db.query(EdgeModel).all()
        return [Edge(**row.to_dict()) for row in rows]


_CHAR_SUBS: dict[str, str] = {
    "Å": "angstrom",
    "å": "angstrom",
    "µ": "micro",
    "μ": "micro",
    "°": "deg",
    "±": "plus-minus",
    "×": "x",
    "·": "-",
}


def _slug(title: str) -> str:
    import unicodedata
    for sym, replacement in _CHAR_SUBS.items():
        title = title.replace(sym, f" {replacement} ")
    parts: list[str] = []
    for ch in unicodedata.normalize("NFKD", title):
        if ch.isascii():
            parts.append(ch)
        elif unicodedata.combining(ch):
            pass
        else:
            name = unicodedata.name(ch, "").lower()
            parts.append(name.split()[-1] if name else "")
    slug = "".join(parts).lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
