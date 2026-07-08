from __future__ import annotations

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.storage.repository import EdgeRepository, EntryRepository


def reload_graph_from_session(db: Session, graph: KnowDoGraph) -> tuple[int, int]:
    entries = EntryRepository(db).get_all()
    edges = EdgeRepository(db).get_all()
    graph.rebuild_from_db(entries, edges)
    return len(entries), len(edges)
