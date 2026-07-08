from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core.retrieval import vector_store
from core.retrieval.embedder import build_embedding_text, get_default_embedder, text_hash
from core.schemas.entry import Entry

logger = logging.getLogger(__name__)


def refresh_entry_embedding_after_commit(db: Session, entry: Entry, model) -> None:
    """Best-effort embedding refresh after the entry row has been committed."""
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
