from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from core.app_state import graph as _graph

router = APIRouter()


class _SSEResponse(StreamingResponse):
    """StreamingResponse that swallows CancelledError on server shutdown.

    Starlette's listen_for_disconnect task raises CancelledError (a BaseException,
    not Exception) when uvicorn force-cancels connections after the graceful-shutdown
    timeout. That bypasses Starlette's internal `wrap()` handler and reaches uvicorn's
    error logger, producing a spurious "Exception in ASGI application" traceback.
    Catching it here keeps the log clean; all generator finally-blocks still run
    because the stack unwinds normally before we get here.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except asyncio.CancelledError:
            pass


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
async def graph_events():
    """Server-Sent Events stream — pushes graph change notifications in real time.

    Events have the shape: ``{"type": "node_added"|"node_updated"|"node_removed", "data": {...}}``
    A ``{"type": "ping"}`` keepalive is emitted every ~25 s.
    """
    from core import events as _events

    async def generator():
        q = _events.subscribe()
        ticks_since_ping = 0
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=1.0)
                    if msg is _events.SHUTDOWN_SENTINEL:
                        return
                    yield f"data: {msg}\n\n"
                    ticks_since_ping = 0
                except asyncio.TimeoutError:
                    ticks_since_ping += 1
                    if ticks_since_ping >= 25:
                        yield 'data: {"type":"ping"}\n\n'
                        ticks_since_ping = 0
        except asyncio.CancelledError:
            raise
        finally:
            _events.unsubscribe(q)

    return _SSEResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
