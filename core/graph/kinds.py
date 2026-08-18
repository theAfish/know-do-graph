"""Database-driven graph-kind detection and capability boundaries.

The storage schema is deliberately shared: a custom graph can use the normal
``entries``/``edges`` tables while defining its own node types.  The graph kind
controls whether Know-Do Graph semantics, especially progressive L1--L4
retrieval, apply to those types.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from core.schemas.entry import EntryType


class GraphKind(str, Enum):
    KNOW_DO_GRAPH = "know_do_graph"
    CUSTOM = "custom"


_METADATA_TABLE = "graph_metadata"


def detected_graph_kind(engine: Engine) -> GraphKind:
    """Determine graph semantics from the database itself.

    ``graph_metadata.graph_kind`` is an explicit, durable declaration for
    ambiguous custom graphs. Without it, any entry type outside the native KDG
    enum makes the database a Custom Graph. A database containing only native
    types remains a Know-Do Graph by default.
    """
    tables = set(inspect(engine).get_table_names())
    if _METADATA_TABLE in tables:
        with engine.connect() as conn:
            declared = conn.execute(
                text("SELECT value FROM graph_metadata WHERE key = 'graph_kind' LIMIT 1")
            ).scalar_one_or_none()
        if declared:
            try:
                return GraphKind(str(declared))
            except ValueError as exc:
                raise ValueError(f"Invalid graph_metadata graph_kind: {declared!r}") from exc

    if "entries" not in tables:
        return GraphKind.KNOW_DO_GRAPH
    native_types = {entry_type.value for entry_type in EntryType}
    with engine.connect() as conn:
        types = conn.execute(text("SELECT DISTINCT entry_type FROM entries")).scalars()
        if any(entry_type and entry_type not in native_types for entry_type in types):
            return GraphKind.CUSTOM
    return GraphKind.KNOW_DO_GRAPH


def uses_know_do_semantics(engine: Engine) -> bool:
    """Whether L1--L4 typing and progressive retrieval are valid."""
    return detected_graph_kind(engine) is GraphKind.KNOW_DO_GRAPH
