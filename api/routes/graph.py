from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from api.schemas import (
    GraphDataResponse,
    GraphPathResponse,
    GraphReloadResponse,
    GraphStatsResponse,
)
from core.app_state import graph as _graph
from core.graph.datasets import get_dataset_adapter
from core.graph.kinds import GraphKind, detected_graph_kind
from core.schemas.entry import EntryType
from core.storage.database import engine, get_db
from core.storage.models import EntryModel

router = APIRouter()


def _dataset_adapter():
    if detected_graph_kind(engine) is GraphKind.CUSTOM:
        return None
    return get_dataset_adapter(engine, entry_count=_graph._g.number_of_nodes())


def _native_dataset_description() -> dict:
    kind = detected_graph_kind(engine)
    if kind is GraphKind.CUSTOM:
        with engine.connect() as conn:
            entry_types = [
                row[0]
                for row in conn.execute(
                    select(EntryModel.entry_type).distinct().order_by(EntryModel.entry_type)
                )
                if row[0]
            ]
        return {
            "kind": kind.value,
            "label": "Custom graph",
            "read_only": False,
            "capabilities": ["graph"],
            "entry_types": entry_types,
            "controls": [],
            "levels": [],
        }
    return {
        "kind": kind.value,
        "label": "Know-Do Graph",
        "read_only": False,
        "capabilities": ["graph", "progressive_retrieval"],
        "entry_types": [entry_type.value for entry_type in EntryType],
        "controls": [],
        "levels": [],
    }


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


@router.get("/stats", response_model=GraphStatsResponse)
def graph_stats() -> GraphStatsResponse:
    """Return high-level graph statistics."""
    adapter = _dataset_adapter()
    if adapter:
        description = adapter.describe()
        level = next(
            item for item in description["levels"] if item["level"] == description["default_level"]
        )
        return {
            "nodes": level["nodes"],
            "edges": level["edges"],
            "is_dag": False,
            "unreviewed_nodes": 0,
        }
    return _graph.stats()


@router.get("/dataset")
def describe_graph_dataset() -> dict:
    """Describe graph kind and any read-only dataset view controls."""
    adapter = _dataset_adapter()
    return adapter.describe() if adapter else _native_dataset_description()


@router.get("/path", response_model=GraphPathResponse)
def find_path(source: str, target: str, cutoff: int = 6) -> GraphPathResponse:
    """Find all simple paths between two entry IDs."""
    paths = _graph.find_paths(source, target, cutoff=cutoff)
    return {"source": source, "target": target, "paths": paths}


@router.get("/subgraph/{entry_id}", response_model=GraphDataResponse)
def get_subgraph(entry_id: str, depth: int = 2) -> GraphDataResponse:
    """Return the ego-subgraph centred on *entry_id* up to *depth* hops."""
    sg = _graph.get_subgraph(entry_id, depth=depth)
    return {
        "metadata": {},
        "nodes": [{"id": n, **d} for n, d in sg.nodes(data=True)],
        "edges": [{"source": u, "target": v, **d} for u, v, d in sg.edges(data=True)],
    }


@router.get("/full", response_model=GraphDataResponse)
def get_full_graph(request: Request) -> GraphDataResponse:
    """Return all nodes and edges in the graph."""
    adapter = _dataset_adapter()
    if adapter:
        try:
            return adapter.graph_view(dict(request.query_params))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"metadata": _graph.stats(), **_graph.full_dump()}


@router.get("/search", response_model=GraphDataResponse)
def search_graph(request: Request) -> GraphDataResponse:
    """Search a read-only dataset without its overview sampling bound."""
    adapter = _dataset_adapter()
    if not adapter or "search" not in adapter.describe().get("capabilities", []):
        raise HTTPException(
            status_code=404, detail="The current graph does not expose dataset search."
        )
    try:
        return adapter.search_view(dict(request.query_params))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hierarchy/{node_id}", response_model=GraphDataResponse)
def get_hierarchy(node_id: str, request: Request) -> GraphDataResponse:
    """Return a standardized parent-to-constituent view when supported."""
    adapter = _dataset_adapter()
    if not adapter or "hierarchy" not in adapter.describe().get("capabilities", []):
        raise HTTPException(
            status_code=404, detail="The current graph does not expose a hierarchy."
        )
    try:
        return adapter.hierarchy_view(node_id=node_id, options=dict(request.query_params))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reload", response_model=GraphReloadResponse)
def reload_graph(db: Session = Depends(get_db)) -> GraphReloadResponse:
    """Rebuild the in-memory graph from the DB and broadcast a refresh event.

    Useful after out-of-process writes (CLI extract, db merge, manual sqlite
    edits) when you don't want to wait for the DB-watcher tick.
    """
    from core import events as _events
    from core.sync.db_watcher import reload_graph_from_db

    nodes, edges = reload_graph_from_db(_graph, db)
    _events.emit("graph_changed", {"source": "reload_endpoint", "nodes": nodes, "edges": edges})
    return {"reloaded": True, "nodes": nodes, "edges": edges}


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
