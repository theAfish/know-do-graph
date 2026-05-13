from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from core.schemas.edge import Edge
from core.schemas.entry import Entry


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


class EntryRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, entry: Entry) -> Entry:
        from core.storage.models import EntryModel

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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return Entry(**model.to_dict())

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
        model.updated_at = datetime.utcnow()
        self._db.commit()
        self._db.refresh(model)
        return Entry(**model.to_dict())

    def delete(self, entry_id: str) -> bool:
        from core.storage.models import EntryModel

        model = self._db.get(EntryModel, entry_id)
        if not model:
            return False
        self._db.delete(model)
        self._db.commit()
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
        return edge

    def delete(self, edge_id: str) -> bool:
        from core.storage.models import EdgeModel

        model = self._db.get(EdgeModel, edge_id)
        if not model:
            return False
        self._db.delete(model)
        self._db.commit()
        return True

    def get_all(self) -> list[Edge]:
        from core.storage.models import EdgeModel

        rows = self._db.query(EdgeModel).all()
        return [Edge(**row.to_dict()) for row in rows]


def _slug(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
