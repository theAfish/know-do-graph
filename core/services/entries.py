from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.entry import Entry, EntryMetadata, EntryType
from core.services.errors import NotFoundError
from core.storage.repository import EntryRepository


def create_entry(
    db: Session,
    graph: KnowDoGraph,
    *,
    title: str,
    content: str = "",
    entry_type: EntryType | str = EntryType.generic,
    tags: Iterable[str] | None = None,
    aliases: Iterable[str] | None = None,
    metadata: EntryMetadata | dict[str, Any] | None = None,
    **fields: Any,
) -> Entry:
    entry = Entry(
        title=title,
        content=content,
        entry_type=EntryType(entry_type),
        tags=list(tags or []),
        aliases=list(aliases or []),
        metadata=_metadata(metadata),
        **fields,
    )
    saved = EntryRepository(db).create(entry)
    graph.add_entry(saved)
    return saved


def persist_entry(db: Session, graph: KnowDoGraph, entry: Entry) -> Entry:
    saved = EntryRepository(db).create(entry)
    graph.add_entry(saved)
    return saved


def update_entry(
    db: Session,
    graph: KnowDoGraph,
    identifier: str,
    **changes: Any,
) -> Entry:
    current = resolve_required(db, graph, identifier)
    if "entry_type" in changes:
        changes["entry_type"] = EntryType(changes["entry_type"])
    if "metadata" in changes:
        changes["metadata"] = _metadata(changes["metadata"])
    updated = current.model_copy(update=changes, deep=True)
    updated.refresh_refs()
    updated._sync_scripts_and_assets()
    return replace_entry(db, graph, updated)


def replace_entry(db: Session, graph: KnowDoGraph, entry: Entry) -> Entry:
    saved = EntryRepository(db).update(entry)
    if saved is None:
        raise NotFoundError(f"Entry not found: {entry.id}")
    graph.add_entry(saved)
    return saved


def delete_entry(db: Session, graph: KnowDoGraph, identifier: str) -> bool:
    entry = RetrievalEngine(db, graph).resolve_identifier(identifier)
    if entry is None:
        return False
    deleted = EntryRepository(db).delete(entry.id)
    if deleted:
        graph.remove_entry(entry.id)
    return deleted


def resolve_required(db: Session, graph: KnowDoGraph, identifier: str) -> Entry:
    entry = RetrievalEngine(db, graph).resolve_identifier(identifier)
    if entry is None:
        raise NotFoundError(f"Entry not found: {identifier}")
    return entry


def _metadata(value: EntryMetadata | dict[str, Any] | None) -> EntryMetadata:
    if value is None:
        return EntryMetadata()
    if isinstance(value, EntryMetadata):
        return value
    return EntryMetadata(**value)
