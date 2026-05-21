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

    ═══ SUBMIT KNOWLEDGE FOR LATER DISTILLATION ══════════════════════

    # Deposit a plain-text summary or context dump into the inbox:
    curl -X POST http://{host}/remote/submit \\
         -H "Content-Type: application/json" \\
         -d '{{"title": "MACE geometry optimisation walkthrough",
              "content": "...",
              "agent_id": "matcreator-01"}}'

    # Deposit an OpenAI-style conversation transcript:
    curl -X POST http://{host}/remote/submit \\
         -H "Content-Type: application/json" \\
         -d '{{"title": "ASE relaxation session",
              "format": "openai",
              "messages": [{{"role":"user","content":"..."}},
                           {{"role":"assistant","content":"..."}}],
              "agent_id": "matcreator-01"}}'

    # Check what is waiting in the inbox:
    curl "http://{host}/remote/inbox"

    # Trigger distillation — the graph agent processes the inbox and creates nodes:
    curl -X POST http://{host}/remote/distill \\
         -H "Content-Type: application/json" \\
         -d '{{}}'

    # Dry-run: preview the distillation prompt without touching the graph:
    curl -X POST http://{host}/remote/distill \\
         -H "Content-Type: application/json" \\
         -d '{{"dry_run": true}}'

    # Clear session history:
    curl -X DELETE http://{host}/remote/session/agent-01

    ═══ ENDPOINTS ═══════════════════════════════════════════════════════

    GET  /                           — This instruction sheet (plain text)
    GET  /remote                     — Same instruction sheet
    GET  /health                     — Server health + graph stats (JSON)
    GET  /docs                       — Interactive API explorer (OpenAPI)

    POST /remote/chat                — Chat with the orchestrator agent (read-only)
    GET  /remote/search              — Search entries
    GET  /remote/graph               — Graph stats + full node/edge list
    GET  /remote/entry/{{id}}          — Entry by ID, slug, or alias
    GET  /remote/entry/{{id}}/related  — Related entries (BFS)
    POST /remote/feedback            — Free-form trace; optionally also updates an entry
    POST /entries/{{id}}/feedback      — Direct verification feedback on a node
    GET  /entries/{{id}}/download      — Download a script entry's source code
    DELETE /remote/session/{{id}}      — Clear a session's chat history

    POST /remote/submit              — Deposit raw knowledge into the inbox
    GET  /remote/inbox               — List pending inbox submissions
    POST /remote/distill             — Run graph agent to convert inbox into nodes

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


class SubmitRequest(BaseModel):
    """Payload for POST /remote/submit.

    External agents use this to deposit raw knowledge (text, conversation
    transcripts, summaries) into the graph's inbox for later distillation.

    At least one of ``content`` or ``messages`` must be provided.
    """
    session_id: Optional[str] = None   # groups submissions; auto-generated if omitted
    title: Optional[str] = None        # short label for what this submission is about
    content: Optional[str] = None      # plain-text content or summary
    # Structured message arrays — supply one of these *instead of* content when
    # you have a conversation transcript.
    messages: Optional[list[dict]] = None  # OpenAI / AutoGen format messages list
    format: str = "text"               # "text" | "openai" | "autogen"
    tags: list[str] = []
    agent_id: Optional[str] = None     # identifies the submitting agent


class DistillRequest(BaseModel):
    """Payload for POST /remote/distill."""
    session_id: Optional[str] = None   # if given, distil only that session's inbox
    model: Optional[str] = None        # LLM model override for the distillation agent
    dry_run: bool = False              # if True, return the prompt without running the agent


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

    agent = OrchestratorAgent(graph=_graph, model=body.model, read_only=True)

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
    if not engine.get_entry_by_id(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
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


# ── Inbox / distillation ──────────────────────────────────────────────────────

_INBOX_SESSION = "inbox"   # MemGraph session used for all submit() entries
_INBOX_TAG = "pending-distillation"


@router.post(
    "/submit",
    status_code=201,
    summary="Submit raw knowledge for later distillation into the graph",
    tags=["remote"],
)
def remote_submit(body: SubmitRequest) -> dict:
    """Deposit raw content from an external agent into the knowledge inbox.

    The submission is stored as a ``MemEntry`` (tagged ``pending-distillation``)
    and is *not* immediately added to the graph.  A human or automated agent
    can later call ``POST /remote/distill`` to process the inbox.

    Supported formats
    -----------------
    * ``format="text"`` (default) — plain ``content`` string.
    * ``format="openai"``         — ``messages`` list of OpenAI-style dicts.
    * ``format="autogen"``        — ``messages`` list of AutoGen-style dicts.
    """
    if not body.content and not body.messages:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Provide 'content' or 'messages'.")

    session_id = body.session_id or _INBOX_SESSION
    mem = MemGraph(session_id=session_id)

    extra_tags = list(body.tags) + [_INBOX_TAG]
    if body.agent_id:
        extra_tags.append(f"agent:{body.agent_id}")

    if body.format in ("openai", "autogen") and body.messages:
        if body.format == "openai":
            entries = mem.ingest_openai_messages(body.messages, tags=extra_tags, as_single_trace=True)
        else:
            entries = mem.ingest_autogen_messages(body.messages, tags=extra_tags, as_single_trace=True)
        # Prepend a title line if given
        if body.title and entries:
            entries[0].content = f"# {body.title}\n\n{entries[0].content}"
            mem._save()
        ids = [e.id for e in entries]
    else:
        content = body.content or ""
        if body.title:
            content = f"# {body.title}\n\n{content}"
        entry = mem.add(content=content, tags=extra_tags)
        ids = [entry.id]

    return {"submitted": True, "ids": ids, "session_id": session_id, "tag": _INBOX_TAG}


@router.get(
    "/inbox",
    summary="List pending knowledge submissions awaiting distillation",
    tags=["remote"],
)
def remote_inbox(session_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Return all MemEntries tagged ``pending-distillation`` that have not yet
    been promoted into the knowledge graph.

    Pass ``session_id`` to scope results to a specific agent's session; omit
    it to see all sessions' pending submissions.
    """
    sessions = [session_id] if session_id else MemGraph.list_sessions()
    results: list[dict] = []
    for sid in sessions:
        mem = MemGraph(session_id=sid)
        for e in mem.list():
            if _INBOX_TAG in e.tags and not e.promoted:
                results.append({
                    "id": e.id,
                    "session_id": e.session_id,
                    "title": (e.content.splitlines()[0].lstrip("# ") if e.content else ""),
                    "preview": e.content[:300] if e.content else "",
                    "tags": e.tags,
                    "created_at": e.created_at.isoformat(),
                    "source_format": e.source_format,
                })
    results.sort(key=lambda x: x["created_at"])
    return results[:limit]


@router.post(
    "/distill",
    summary="Distil pending inbox submissions into knowledge graph nodes",
    tags=["remote"],
)
def remote_distill(body: DistillRequest) -> dict:
    """Run the GraphAgent over all pending inbox submissions and convert them
    into proper graph nodes.

    The agent will:
    1. Read each pending submission.
    2. Decide which capabilities/procedures/tools to extract.
    3. Call ``create_entry``, ``create_edge``, etc. to persist them.
    4. Return a summary of what was created.

    Processed entries are marked ``promoted`` in the inbox so they are not
    distilled again.

    Set ``dry_run=true`` to preview the distillation prompt without executing it.
    """
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")

    sessions = [body.session_id] if body.session_id else MemGraph.list_sessions()

    # Collect all un-promoted inbox entries
    pending: list[tuple[MemGraph, str, str]] = []  # (mem, entry_id, content)
    for sid in sessions:
        mem = MemGraph(session_id=sid)
        for e in mem.list():
            if _INBOX_TAG in e.tags and not e.promoted:
                pending.append((mem, e.id, e.content))

    if not pending:
        return {"distilled": 0, "message": "Inbox is empty — nothing to distill."}

    # Build a prompt that presents all submissions to the GraphAgent
    blocks = []
    for i, (_, eid, content) in enumerate(pending, 1):
        blocks.append(f"--- Submission {i} (id: {eid}) ---\n{content}")
    combined = "\n\n".join(blocks)

    prompt = (
        "The following raw knowledge submissions were sent by external agents. "
        "Please extract the reusable capabilities, procedures, tools, and "
        "relationships they describe, and add them to the knowledge graph as "
        "properly structured nodes. Follow the abstraction rules: create generic "
        "nodes, not overly-specific instances. Skip anything that is conversational "
        "filler or not worth a standalone node. After processing, briefly list what "
        "was created.\n\n"
        + combined
    )

    if body.dry_run:
        return {"dry_run": True, "pending_count": len(pending), "prompt": prompt}

    from agents.graph_agent.agent import GraphAgent
    agent = GraphAgent(graph=_graph, model=body.model)
    response = agent.chat(prompt)

    # Mark all processed entries as promoted
    for mem, eid, _ in pending:
        mem.mark_promoted(eid, target_id="distilled")

    return {
        "distilled": len(pending),
        "response": response,
    }

