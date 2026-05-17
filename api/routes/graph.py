from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

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


@router.get("/events")
async def graph_events(request: Request):
    """Server-Sent Events stream — pushes graph change notifications in real time.

    Events have the shape: ``{"type": "node_added"|"node_updated"|"node_removed", "data": {...}}``
    A ``{"type": "ping"}`` keepalive is emitted every ~25 s.
    """
    from core import events as _events

    async def generator():
        q = _events.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            _events.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
