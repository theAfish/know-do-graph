"""Mem-Graph HTTP routes.

Agents can POST session memory into the system in any supported format
and later list, promote, or delete traces.

Ingestion endpoint summary
---------------------------
POST /mem/{session_id}/add              — plain text trace
POST /mem/{session_id}/ingest/openai    — OpenAI-style messages list
POST /mem/{session_id}/ingest/langchain — LangChain-style messages list
POST /mem/{session_id}/ingest/autogen   — AutoGen messages list
POST /mem/{session_id}/ingest/raw       — arbitrary JSON object / array
GET  /mem/{session_id}                  — list all traces for a session
GET  /mem/sessions                      — list all known session IDs
DELETE /mem/{session_id}/{mem_id}       — delete a single trace
POST /mem/{session_id}/{mem_id}/promote — promote trace → KDG entry
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.schemas import EdgeListResponse, Entry, MemoryTraceListResponse, PaginationMeta
from core.memory.memgraph import MemEntry
from core.schemas.edge import Edge

router = APIRouter()


# ------------------------------------------------------------------
# Request bodies
# ------------------------------------------------------------------


class AddRequest(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)
    success: Optional[bool] = None


class MessagesRequest(BaseModel):
    messages: list[dict[str, Any]]
    tags: list[str] = Field(default_factory=list)
    as_single_trace: bool = True


class RawIngestRequest(BaseModel):
    data: Any
    tags: list[str] = Field(default_factory=list)
    as_single_trace: bool = True


class PromoteRequest(BaseModel):
    entry_type: str = "generic"
    tags: list[str] = Field(default_factory=list)


class ConnectRequest(BaseModel):
    source_id: str
    target_id: str
    relation: str = "related_memory"
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@router.get("/sessions", response_model=list[str], tags=["mem"])
def list_sessions():
    """Return all session IDs that have persisted memory."""
    from core.memory.memgraph import MemGraph

    return MemGraph.list_sessions()


@router.get("/{session_id}", response_model=MemoryTraceListResponse, tags=["mem"])
def list_traces(session_id: str):
    """List all memory traces for a session."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    items = mg.list()
    return {
        "items": items,
        "pagination": PaginationMeta(limit=len(items), count=len(items)),
        "session_id": session_id,
    }


@router.post("/{session_id}/add", response_model=MemEntry, status_code=201, tags=["mem"])
def add_trace(session_id: str, body: AddRequest):
    """Add a single plain-text observation."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    entry = mg.add(body.content, tags=body.tags, success=body.success)
    return entry


@router.post(
    "/{session_id}/ingest/openai", response_model=list[MemEntry], status_code=201, tags=["mem"]
)
def ingest_openai(session_id: str, body: MessagesRequest):
    """Ingest an OpenAI-style ``[{"role": ..., "content": ...}]`` messages list."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    entries = mg.ingest_openai_messages(
        body.messages, tags=body.tags, as_single_trace=body.as_single_trace
    )
    return entries


@router.post(
    "/{session_id}/ingest/langchain", response_model=list[MemEntry], status_code=201, tags=["mem"]
)
def ingest_langchain(session_id: str, body: MessagesRequest):
    """Ingest LangChain-style message objects (normalised to role/content dicts)."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    entries = mg.ingest_langchain_messages(
        body.messages, tags=body.tags, as_single_trace=body.as_single_trace
    )
    return entries


@router.post(
    "/{session_id}/ingest/autogen", response_model=list[MemEntry], status_code=201, tags=["mem"]
)
def ingest_autogen(session_id: str, body: MessagesRequest):
    """Ingest AutoGen / multi-agent conversation records (``name`` + ``content`` dicts)."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    entries = mg.ingest_autogen_messages(
        body.messages, tags=body.tags, as_single_trace=body.as_single_trace
    )
    return entries


@router.post(
    "/{session_id}/ingest/raw", response_model=list[MemEntry], status_code=201, tags=["mem"]
)
def ingest_raw(session_id: str, body: RawIngestRequest):
    """Ingest arbitrary JSON.

    - JSON array → treated as OpenAI/AutoGen message list
    - JSON object with ``messages`` / ``history`` / ``conversation`` key → that list is extracted
    - Anything else → stored as a single serialised trace
    """
    import json as _json

    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    # Reuse ingest_file logic by round-tripping through a temp in-memory path
    # equivalent: replicate the dict-dispatch logic directly
    data = body.data
    if isinstance(data, list):
        entries = mg.ingest_openai_messages(
            data, tags=body.tags, as_single_trace=body.as_single_trace
        )
    elif isinstance(data, dict):
        for key in ("messages", "history", "conversation", "turns"):
            if key in data and isinstance(data[key], list):
                entries = mg.ingest_openai_messages(
                    data[key], tags=body.tags, as_single_trace=body.as_single_trace
                )
                break
        else:
            entry = mg.add(
                content=_json.dumps(data, indent=2, default=str),
                tags=body.tags,
            )
            entries = [entry]
    else:
        entry = mg.add(str(data), tags=body.tags)
        entries = [entry]
    return entries


@router.delete("/{session_id}/{mem_id}", status_code=204, tags=["mem"])
def delete_trace(session_id: str, mem_id: str):
    """Delete a single memory trace."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session_id)
    if not mg.delete(mem_id):
        raise HTTPException(status_code=404, detail="Memory trace not found")


@router.get("/{session_id}/edges", response_model=EdgeListResponse, tags=["mem"])
def list_memory_edges(session_id: str, mem_id: Optional[str] = None):
    """List memory-to-memory edges touching nodes in a session."""
    from core.memory.memgraph import MemGraph

    items = MemGraph(session_id).edges(mem_id)
    return {
        "items": items,
        "pagination": PaginationMeta(limit=len(items), count=len(items)),
    }


@router.post("/{session_id}/edges", response_model=Edge, status_code=201, tags=["mem"])
def connect_memory(session_id: str, body: ConnectRequest):
    """Create a typed edge between two memory nodes."""
    from core.memory.memgraph import MemGraph

    try:
        edge = MemGraph(session_id).connect(
            body.source_id,
            body.target_id,
            relation=body.relation,
            weight=body.weight,
            metadata=body.metadata,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return edge


@router.post("/{session_id}/{mem_id}/promote", response_model=Entry, tags=["mem"])
def promote_trace(session_id: str, mem_id: str, body: PromoteRequest):
    """Promote a memory trace into a full Know-Do Graph entry."""
    from agents.maintenance_agent.agent import MaintenanceAgent
    from core.app_state import graph
    from core.schemas.entry import EntryType
    from core.storage.database import init_db

    init_db()
    agent = MaintenanceAgent(graph)
    entry = agent.promote_mem_entry(
        mem_id,
        session_id=session_id,
        entry_type=EntryType(body.entry_type),
        tags=body.tags or None,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Memory trace not found")
    return entry
