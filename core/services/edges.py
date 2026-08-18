from __future__ import annotations

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.schemas.edge import Edge, EdgeRelation
from core.services.entries import resolve_required
from core.services.errors import NotFoundError, ValidationServiceError
from core.storage.models import EdgeModel
from core.storage.repository import EdgeRepository


def connect_entries(
    db: Session,
    graph: KnowDoGraph,
    source: str,
    target: str,
    *,
    relation: EdgeRelation | str = EdgeRelation.related_workflow,
    weight: float = 1.0,
    metadata: dict | None = None,
) -> Edge:
    source_entry = resolve_required(db, graph, source)
    target_entry = resolve_required(db, graph, target)
    if source_entry.id == target_entry.id:
        raise ValidationServiceError("Self-loop edges are not allowed.", code="self_loop_rejected")

    try:
        relation_value = EdgeRelation(relation)
    except ValueError:
        relation_value = EdgeRelation.wikilink

    edge = Edge(
        source_id=source_entry.id,
        target_id=target_entry.id,
        relation=relation_value,
        weight=weight,
        metadata=metadata or {},
    )
    saved = EdgeRepository(db).create(edge)
    graph.add_edge(saved)
    return saved


def delete_edge(db: Session, graph: KnowDoGraph, edge_id: str) -> bool:
    model = db.get(EdgeModel, edge_id)
    if model is None:
        raise NotFoundError(f"Edge not found: {edge_id}")
    source_id, target_id = model.source_id, model.target_id
    deleted = EdgeRepository(db).delete(edge_id)
    if deleted:
        graph.remove_edge(source_id, target_id)
    return deleted
