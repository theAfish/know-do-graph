"""Thin wrapper around the sqlite-vec `entry_embeddings` virtual table.

All operations are no-ops when sqlite-vec is not loaded — callers can use
the wrapper unconditionally and let it degrade silently. The virtual table
itself is created in ``core.storage.database.init_db``.
"""

from __future__ import annotations

import logging
import struct
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _pack(vec: list[float]) -> bytes:
    """sqlite-vec accepts vectors as little-endian float32 blobs."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _table_available(db: Session) -> bool:
    """Cheap probe — returns True iff the vec0 virtual table is queryable."""
    try:
        db.execute(text("SELECT entry_id FROM entry_embeddings LIMIT 0"))
        return True
    except Exception:
        return False


def upsert(db: Session, entry_id: str, vec: list[float]) -> bool:
    if not vec or not _table_available(db):
        return False
    try:
        blob = _pack(vec)
        db.execute(text("DELETE FROM entry_embeddings WHERE entry_id = :id"), {"id": entry_id})
        db.execute(
            text("INSERT INTO entry_embeddings (entry_id, embedding) VALUES (:id, :v)"),
            {"id": entry_id, "v": blob},
        )
        db.commit()
        return True
    except Exception as exc:
        logger.warning("vector upsert failed for %s: %s", entry_id, exc)
        db.rollback()
        return False


def delete(db: Session, entry_id: str) -> None:
    if not _table_available(db):
        return
    try:
        db.execute(text("DELETE FROM entry_embeddings WHERE entry_id = :id"), {"id": entry_id})
        db.commit()
    except Exception:
        db.rollback()


def knn(db: Session, vec: list[float], k: int = 50) -> list[tuple[str, float]]:
    """Return ``[(entry_id, distance), ...]`` ordered by ascending distance.

    Empty list if the index is unavailable or empty.
    """
    if not vec or not _table_available(db):
        return []
    try:
        blob = _pack(vec)
        rows = db.execute(
            text(
                "SELECT entry_id, distance FROM entry_embeddings "
                "WHERE embedding MATCH :v AND k = :k "
                "ORDER BY distance"
            ),
            {"v": blob, "k": int(k)},
        ).all()
        return [(r[0], float(r[1])) for r in rows]
    except Exception as exc:
        logger.warning("vector knn query failed: %s", exc)
        return []


def count(db: Session) -> Optional[int]:
    if not _table_available(db):
        return None
    try:
        return int(db.execute(text("SELECT COUNT(*) FROM entry_embeddings")).scalar() or 0)
    except Exception:
        return None
