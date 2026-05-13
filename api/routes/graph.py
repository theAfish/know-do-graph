from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.app_state import graph as _graph

router = APIRouter()


@router.get("/stats")
def graph_stats() -> dict:
    """Return high-level graph statistics."""
    return _graph.stats()


@router.get("/path")
def find_path(source: str, target: str, cutoff: int = 6) -> dict:
    """Find all simple paths between two entry IDs."""
    paths = _graph.find_paths(source, target, cutoff=cutoff)
    return {"source": source, "target": target, "paths": paths}


@router.get("/subgraph/{entry_id}")
def get_subgraph(entry_id: str, depth: int = 2) -> dict:
    """Return the ego-subgraph centred on *entry_id* up to *depth* hops."""
    sg = _graph.get_subgraph(entry_id, depth=depth)
    return {
        "nodes": [{"id": n, **d} for n, d in sg.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, **d}
            for u, v, d in sg.edges(data=True)
        ],
    }


@router.get("/full")
def get_full_graph() -> dict:
    """Return all nodes and edges in the graph."""
    g = _graph._g
    return {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, **d}
            for u, v, d in g.edges(data=True)
        ],
    }


@router.get("/neighbors/{entry_id}")
def get_neighbors(
    entry_id: str,
    direction: str = "both",
) -> list[dict]:
    """Return immediate neighbors of *entry_id*."""
    return _graph.get_neighbors(entry_id, direction=direction)
