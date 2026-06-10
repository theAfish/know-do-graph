"""Cross-process DB-change watcher.

Polls a cheap fingerprint of the entries/edges tables every few seconds; when
it changes (e.g. a CLI command wrote to the same SQLite file) the in-memory
:class:`KnowDoGraph` is rebuilt and a ``graph_changed`` SSE event is broadcast
so connected UIs refresh automatically.

Disabled by setting ``KDG_DB_WATCH_INTERVAL_SECONDS=0``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import text

from core import events as _events
from core.storage.database import SessionLocal

logger = logging.getLogger(__name__)


def _fingerprint(db) -> tuple:
    """Cheap change-detector: row counts + max(updated_at)/created_at."""
    e_count = db.execute(text("SELECT COUNT(*) FROM entries")).scalar() or 0
    e_max = db.execute(text("SELECT MAX(updated_at) FROM entries")).scalar() or ""
    ed_count = db.execute(text("SELECT COUNT(*) FROM edges")).scalar() or 0
    ed_max = db.execute(text("SELECT MAX(created_at) FROM edges")).scalar() or ""
    return (int(e_count), str(e_max), int(ed_count), str(ed_max))


def reload_graph_from_db(graph) -> tuple[int, int]:
    """Rebuild *graph* from the current DB contents. Returns (node_count, edge_count).

    Also opportunistically deletes any dangling edges (edges whose source or
    target entry no longer exists). Such rows produced "ghost" nodes in the
    UI in earlier versions; pruning them here keeps the graph self-healing.
    """
    from core.storage.repository import EdgeRepository, EntryRepository

    with SessionLocal() as db:
        entry_repo = EntryRepository(db)
        edge_repo = EdgeRepository(db)
        entries = entry_repo.get_all()
        entry_ids = {e.id for e in entries}
        all_edges = edge_repo.get_all()
        dangling = [e for e in all_edges if e.source_id not in entry_ids or e.target_id not in entry_ids]
        if dangling:
            for e in dangling:
                edge_repo.delete(e.id)
            logger.warning("reload_graph_from_db: pruned %d dangling edge(s)", len(dangling))
        edges = [e for e in all_edges if e.source_id in entry_ids and e.target_id in entry_ids]
    graph.rebuild_from_db(entries, edges)
    return (len(entries), len(edges))


async def run_db_watcher(graph, interval_seconds: int) -> None:
    """Poll the DB fingerprint on a fixed cadence and reload on change."""
    if interval_seconds <= 0:
        return

    with SessionLocal() as db:
        last = _fingerprint(db)

    logger.info("db-watcher started (interval=%ss, initial=%s)", interval_seconds, last)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            with SessionLocal() as db:
                current = _fingerprint(db)
            if current != last:
                logger.info("db change detected (%s \u2192 %s) \u2014 reloading graph", last, current)
                nodes, edges = reload_graph_from_db(graph)
                _events.emit(
                    "graph_changed",
                    {"source": "db_watcher", "nodes": nodes, "edges": edges},
                )
                last = current
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("db-watcher iteration failed: %s", exc)
