"""Remote agent access routes.

Exposes a simplified, agent-friendly interface for remote clients to:
  - Chat with the orchestrator agent (with optional multi-turn session history)
  - Search and query the knowledge graph
  - Submit feedback / memory traces
  - Browse graph stats

All endpoints live under the ``/remote`` prefix.

The root  GET /  and  GET /remote  both return a plain-text instruction sheet
so that ``curl http://<host>:<port>/`` immediately tells any client how to
interact with the server.
"""

from __future__ import annotations

import os
import textwrap
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.app_state import graph as _graph
from core.memory.memgraph import MemGraph
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import EdgeRelation
from core.schemas.entry import EntryType
from core.storage.database import get_db

router = APIRouter()

# ── In-memory session store ───────────────────────────────────────────────────
# Maps session_id → list of OpenAI-format message dicts (history after system prompt)
_sessions: dict[str, list[dict]] = {}

# ── Instruction text ──────────────────────────────────────────────────────────
_INSTRUCTIONS_TEMPLATE = textwrap.dedent(
    """\
    ╔══════════════════════════════════════════════════════════════════════╗
    ║           Know-Do Graph  —  Remote Agent Access                     ║
    ╚══════════════════════════════════════════════════════════════════════╝

    A wiki-native executable knowledge graph with LLM agents.
    Remote agents and humans can query the graph, chat with agents, and
    submit feedback over plain HTTP.

    ═══ QUICK START ═════════════════════════════════════════════════════

    # Chat with the graph agent (one-shot):
    curl -X POST http://{host}/remote/chat \\
         -H "Content-Type: application/json" \\
         -d '{{"message": "What entries are in the graph?"}}'

    # Multi-turn chat — use a session_id to retain history across calls:
    curl -X POST http://{host}/remote/chat \\
         -H "Content-Type: application/json" \\
         -d '{{"message": "Tell me about procedures", "session_id": "agent-01"}}'

    curl -X POST http://{host}/remote/chat \\
         -H "Content-Type: application/json" \\
         -d '{{"message": "Now show me the dependencies", "session_id": "agent-01"}}'

    # Search the knowledge graph:
    curl "http://{host}/remote/search?q=relaxation&limit=5"

    # Filter by entry type  (capability | procedure | workflow | tool | ...):
    curl "http://{host}/remote/search?entry_type=procedure"

    # Get a specific entry by ID, slug, or alias:
    curl "http://{host}/remote/entry/<id-or-slug>"

    # Get related entries (BFS traversal, default depth=1):
    curl "http://{host}/remote/entry/<id>/related?depth=2"

    # Graph stats + full node/edge dump:
    curl "http://{host}/remote/graph"

    # Submit feedback or observations:
    curl -X POST http://{host}/remote/feedback \\
         -H "Content-Type: application/json" \\
         -d '{{"session_id": "agent-01", "content": "Entry X needs more detail", "tags": ["feedback"]}}'

    # Report that you have TESTED a node and it works (or is bugged).
    # This updates the entry's verification_status and appends to its feedback_log.
    # verdict: works | peer_works | bugged | deprecated | unclear
    curl -X POST http://{host}/entries/<id-or-slug>/feedback \\
         -H "Content-Type: application/json" \\
         -d '{{"verdict": "works", "note": "ran on H2O, converged", "agent_id": "matcreator-01"}}'

    # Or do both in one call — store a memory trace AND update the entry:
    curl -X POST http://{host}/remote/feedback \\
         -H "Content-Type: application/json" \\
         -d '{{"session_id": "agent-01", "content": "MACE relaxation diverged on Cu",
              "entry_id": "mace-relaxation", "verdict": "bugged",
              "agent_id": "matcreator-01"}}'

    # Clear session history:
    curl -X DELETE http://{host}/remote/session/agent-01

    ═══ ENDPOINTS ═══════════════════════════════════════════════════════

    GET  /                           — This instruction sheet (plain text)
    GET  /remote                     — Same instruction sheet
    GET  /health                     — Server health + graph stats (JSON)
    GET  /docs                       — Interactive API explorer (OpenAPI)

    POST /remote/chat                — Chat with the orchestrator agent
    GET  /remote/search              — Search entries
    GET  /remote/graph               — Graph stats + full node/edge list
    GET  /remote/entry/{{id}}          — Entry by ID, slug, or alias
    GET  /remote/entry/{{id}}/related  — Related entries (BFS)
    POST /remote/feedback            — Free-form trace; optionally also updates an entry
    POST /entries/{{id}}/feedback      — Direct verification feedback on a node
    GET  /entries/{{id}}/download      — Download a script entry's source code
    DELETE /remote/session/{{id}}      — Clear a session's chat history

    ═══ NODE VERIFICATION ═══════════════════════════════════════════════

    Every entry has a `verification_status` (unverified by default). When you
    use a skill/procedure node and verify it works (or find it broken),
    POST to /entries/{{id}}/feedback so the graph learns. Verdicts:
      works | peer_works | bugged | deprecated | unclear

    ═══ CHAT REQUEST BODY ═══════════════════════════════════════════════

      {{
        "message":    "Your question or instruction",   // required
        "session_id": "optional-id-for-multi-turn",    // optional
        "model":      "optional-model-override"        // optional
      }}

    Response: {{"response": "...", "session_id": "..."}}

    ═══ FEEDBACK REQUEST BODY ═══════════════════════════════════════════

      {{
        "session_id": "your-session-id",               // required
        "content":    "Your observation or feedback",  // required
        "tags":       ["optional", "tags"],            // optional
        "success":    true | false | null              // optional
      }}

    ═══ SEARCH PARAMETERS ═══════════════════════════════════════════════

      q          — free-text query (title, content, tags)
      tags       — comma-separated tag filter  e.g. tags=python,simulation
      entry_type — one of: capability, procedure, workflow, tool, repository,
                   environment, dependency, data, analytical, memory, generic
      limit      — max results (default 20)

    ═══ NOTES ═══════════════════════════════════════════════════════════

      • OPENAI_API_KEY must be set on the server to use chat endpoints.
        Optionally set OPENAI_API_BASE to point at a custom LLM endpoint.
      • session_id is an arbitrary string; history is kept in server memory
        for the lifetime of the process.
      • For full CRUD access use /entries, /graph, /mem, and /agent routes.
      • Human-readable graph explorer:  http://{host}/ui
      • Full API reference:             http://{host}/docs
    """
)


def _render_instructions(request: Request) -> str:
    host = request.headers.get("host", "localhost:8000")
    return _INSTRUCTIONS_TEMPLATE.format(host=host)


# ── Pydantic request models ───────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None


class FeedbackRequest(BaseModel):
    session_id: str
    content: str
    tags: list[str] = []
    success: Optional[bool] = None
    # When set, the feedback also updates the named entry's verification_status
    # via the same mechanism as POST /entries/{id}/feedback.
    entry_id: Optional[str] = None
    verdict: Optional[str] = None  # works | peer_works | bugged | deprecated | unclear
    agent_id: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_class=PlainTextResponse,
    summary="Remote agent instructions",
    tags=["remote"],
)
@router.get(
    "/",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
def remote_instructions(request: Request) -> PlainTextResponse:
    """Return the plain-text instruction sheet for remote agents and humans."""
    return PlainTextResponse(_render_instructions(request))


@router.post(
    "/chat",
    summary="Chat with the orchestrator agent",
    tags=["remote"],
)
def remote_chat(body: ChatRequest) -> dict:
    """Send a message to the OrchestratorAgent.

    Optionally pass ``session_id`` to maintain conversation history across
    multiple calls.  A new UUID session is created automatically when omitted.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on this server.",
        )

    from agents.orchestrator.agent import OrchestratorAgent

    session_id = body.session_id or str(uuid.uuid4())

    agent = OrchestratorAgent(graph=_graph, model=body.model)

    # Restore prior history (everything after the agent's own system prompt)
    if session_id in _sessions:
        agent._history.extend(_sessions[session_id])

    response = agent.chat(body.message)

    # Persist history for future turns (skip the system prompt at index 0)
    _sessions[session_id] = list(agent._history[1:])

    return {"response": response, "session_id": session_id}


@router.get(
    "/search",
    summary="Search the knowledge graph",
    tags=["remote"],
)
def remote_search(
    q: Optional[str] = None,
    tags: Optional[str] = None,
    entry_type: Optional[EntryType] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Full-text search with optional tag and entry-type filters.

    ``tags`` accepts a comma-separated list, e.g. ``tags=python,simulation``.
    """
    engine = RetrievalEngine(db, _graph)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = engine.search_entries(query=q, tags=tag_list, entry_type=entry_type, limit=limit)
    return [e.model_dump(mode="json") for e in results]


@router.get(
    "/graph",
    summary="Graph statistics and full node/edge list",
    tags=["remote"],
)
def remote_graph_overview() -> dict:
    """Return graph stats (node/edge counts) plus a full dump of all nodes and edges."""
    g = _graph._g
    return {
        **_graph.stats(),
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
    }


@router.get(
    "/entry/{entry_id}",
    summary="Get an entry by ID, slug, or alias",
    tags=["remote"],
)
def remote_get_entry(entry_id: str, db: Session = Depends(get_db)) -> dict:
    """Retrieve a single entry by its UUID, slug, or any registered alias."""
    engine = RetrievalEngine(db, _graph)
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry.model_dump(mode="json")


@router.get(
    "/entry/{entry_id}/related",
    summary="Get entries related to an entry via BFS",
    tags=["remote"],
)
def remote_get_related(
    entry_id: str,
    depth: int = 1,
    relation: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """BFS traversal from ``entry_id`` up to ``depth`` hops.

    Optionally filter by ``relation`` (e.g. ``dependency``, ``wikilink``).
    """
    engine = RetrievalEngine(db, _graph)
    rel: Optional[EdgeRelation] = EdgeRelation(relation) if relation else None
    results = engine.get_related_entries(entry_id, depth=depth, relation=rel)
    return [e.model_dump(mode="json") for e in results]


@router.post(
    "/feedback",
    status_code=201,
    summary="Submit feedback as a memory trace (and optionally update an entry)",
    tags=["remote"],
)
def remote_feedback(body: FeedbackRequest) -> dict:
    """Store feedback as a MemGraph trace.

    If ``entry_id`` and ``verdict`` are supplied, also call ``submit_feedback``
    on that entry so its ``verification_status`` is updated and the event
    appears in the entry's ``feedback_log`` — letting external agents close
    the loop with a single call.
    """
    mem = MemGraph(session_id=body.session_id)
    entry = mem.add(content=body.content, tags=body.tags, success=body.success)
    result: dict = {"id": entry.id, "session_id": body.session_id, "stored": True}

    if body.entry_id and body.verdict:
        from agents.graph_agent.tools import submit_feedback

        fb = submit_feedback(
            entry_id=body.entry_id,
            verdict=body.verdict,
            note=body.content,
            evidence="",
            agent_id=body.agent_id or body.session_id,
            graph=_graph,
        )
        result["entry_feedback"] = fb
    return result


@router.delete(
    "/session/{session_id}",
    status_code=204,
    summary="Clear a session's chat history",
    tags=["remote"],
)
def remote_clear_session(session_id: str) -> None:
    """Remove the in-memory conversation history for the given session."""
    _sessions.pop(session_id, None)
