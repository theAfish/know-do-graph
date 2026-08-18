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
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.routes.remote_instructions import render_remote_instructions
from api.schemas import (
    RemoteAttachedSearchResponse,
    RemoteChatResponse,
    RemoteDistillResponse,
    RemoteEntrySummary,
    RemoteFeedbackResponse,
    RemoteGraphOverviewResponse,
    RemoteInboxItem,
    RemoteSubmitResponse,
)
from core.app_state import graph as _graph
from core.memory.memgraph import MemGraph
from core.retrieval.progressive import ProgressiveRetriever
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import EdgeRelation
from core.schemas.entry import EntryType
from core.services.serialization import _strip_empty as _strip_empty_value
from core.storage.database import get_db

router = APIRouter()

# ── In-memory session store ───────────────────────────────────────────────────
# Maps session_id → list of OpenAI-format message dicts (history after system prompt)
_sessions: dict[str, list[dict]] = {}

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

    session_id: Optional[str] = None  # groups submissions; auto-generated if omitted
    title: Optional[str] = None  # short label for what this submission is about
    content: Optional[str] = None  # plain-text content or summary
    # Structured message arrays — supply one of these *instead of* content when
    # you have a conversation transcript.
    messages: Optional[list[dict]] = None  # OpenAI / AutoGen format messages list
    format: str = "text"  # "text" | "openai" | "autogen"
    tags: list[str] = []
    agent_id: Optional[str] = None  # identifies the submitting agent


class DistillRequest(BaseModel):
    """Payload for POST /remote/distill."""

    session_id: Optional[str] = None  # if given, distil only that session's inbox
    model: Optional[str] = None  # LLM model override for the distillation agent
    dry_run: bool = False  # if True, return the prompt without running the agent


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
    host = request.headers.get("host", "localhost:8000")
    return PlainTextResponse(render_remote_instructions(host))


@router.post(
    "/chat",
    response_model=RemoteChatResponse,
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
    response_model=list[RemoteEntrySummary],
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
    return [_summarize_entry(e) for e in results]


# Metadata fields that are internal / dev-only and not useful to remote agents.
_METADATA_INTERNAL_KEYS = {
    # Sync / maintenance
    "remote_source",
    "custom",
    "feedback_log",
    "needs_generalization",
    "extraction_method",
    "refinement_status",
    "review_count",
    "modify_count",
    "last_reviewed_at",
    # Timestamps — not actionable for consumers
    "timestamp",
}


def _strip_empty(d: dict) -> dict:
    """Recursively remove None values and empty containers from a dict."""
    return _strip_empty_value(d)


def _clean_entry(entry) -> dict:
    """Return a full entry dict with internal/dev-only and empty fields stripped.

    Removes ``remote_source``, ``internal_refs``, ``scripts``, ``assets``,
    noisy metadata sub-fields, and any null/empty values.
    """
    d = entry.model_dump(mode="json")
    # Drop top-level internal fields.
    for key in ("internal_refs", "scripts", "assets"):
        d.pop(key, None)
    # Strip internal sub-fields from metadata.
    meta = d.get("metadata") or {}
    for key in _METADATA_INTERNAL_KEYS:
        meta.pop(key, None)
    d["metadata"] = _strip_empty(meta)
    # Strip null / empty top-level fields (but keep metadata even if empty).
    d = _strip_empty(d)
    if "metadata" not in d:
        d["metadata"] = {}
    return d


def _summarize_entry(entry, snippet_words: int = 40) -> dict:
    """Return a lightweight summary of an entry for search-result listings.

    Includes only identifiers, type/tags, and a short content snippet so that
    agents can decide which entries to fetch in full via ``/remote/entry/<id>``.
    """
    content = (entry.content or "").strip()
    # Skip YAML frontmatter when present so the snippet shows real prose.
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            content = content[end + 4 :].lstrip()
    # Drop heading markers / blank lines from the very top.
    lines = [ln for ln in content.splitlines() if ln.strip()]
    body = " ".join(lines)
    words = body.split()
    snippet = " ".join(words[:snippet_words])
    if len(words) > snippet_words:
        snippet += " …"

    return {
        "id": str(entry.id),
        "title": entry.title,
        "slug": entry.slug,
        "entry_type": entry.entry_type.value
        if hasattr(entry.entry_type, "value")
        else entry.entry_type,
        "tags": list(entry.tags or []),
        "aliases": list(getattr(entry, "aliases", []) or []),
        "snippet": snippet,
    }


@router.get(
    "/graph",
    response_model=RemoteGraphOverviewResponse,
    summary="Graph statistics and full node/edge list",
    tags=["remote"],
)
def remote_graph_overview() -> dict:
    """Return graph stats (node/edge counts) plus a full dump of all nodes and edges."""
    return {**_graph.stats(), **_graph.full_dump()}


@router.get(
    "/entry/{entry_id}",
    summary="Get an entry by ID, slug, or alias",
    tags=["remote"],
)
def remote_get_entry(entry_id: str, db: Session = Depends(get_db)) -> dict:
    """Retrieve a single entry by its UUID, slug, or any registered alias.

    The response is augmented with a ``progressive_hints`` block that tells
    the caller how many L3 heuristics (operational experience) and L4
    constraints (known limitations / failure modes) are **directly attached**
    to this node via graph edges, plus the URLs to fetch them. This lets a
    remote agent decide whether to drill down for additional guidance
    without paying the cost of loading those bodies up front.
    """
    engine = RetrievalEngine(db, _graph)
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    data = _clean_entry(entry)

    retriever = ProgressiveRetriever(db, _graph)
    counts = retriever.count_attached(entry.id)
    data["progressive_hints"] = _build_progressive_hints(entry.id, counts)
    return data


def _build_progressive_hints(entry_id: str, counts: dict) -> dict:
    """Build the progressive-disclosure hint block for a single entry.

    Only counts nodes directly attached via ``heuristic_for`` /
    ``constraint_on`` / ``warning_about`` edges — i.e. the L3/L4 sidecars
    of the **currently watched node**, not the whole graph.
    """
    h = int(counts.get("heuristics", 0))
    c = int(counts.get("constraints", 0))
    hints: dict = {
        "heuristics_count": h,
        "constraints_count": c,
        "heuristics_url": f"/remote/entry/{entry_id}/heuristics",
        "constraints_url": f"/remote/entry/{entry_id}/constraints",
    }
    if h or c:
        hints["message"] = (
            f"This entry has {h} attached heuristic(s) (operational experience) "
            f"and {c} attached constraint(s) (known limitations / failure modes) "
            f"that may guide your subsequent use. "
            f"These endpoints behave like /remote/search but are scoped to the "
            f"nodes attached to THIS entry — pass ?q=<keywords> to narrow down "
            f"(otherwise the top results by usage are returned):\n"
            f"  GET /remote/entry/{entry_id}/heuristics?q=...&limit=10\n"
            f"  GET /remote/entry/{entry_id}/constraints?q=...&limit=10"
        )
    return hints


@router.get(
    "/entry/{entry_id}/heuristics",
    response_model=RemoteAttachedSearchResponse,
    summary="Search L3 heuristics attached to an entry",
    tags=["remote"],
)
def remote_get_heuristics(
    entry_id: str,
    q: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 10,
    mode: str = "hybrid",
    db: Session = Depends(get_db),
) -> dict:
    """Search the L3 heuristics (operational experience) attached to *entry_id*.

    Scope is restricted to nodes connected to this entry via ``heuristic_for``
    edges — so even if the graph contains thousands of L3 nodes overall, only
    the ones attached to this entry are considered.

    - ``q`` — free-text query; uses the same hybrid keyword+vector ranking as
      ``/remote/search``. Omit to get the top results by usage_count.
    - ``tags`` — comma-separated tag filter.
    - ``limit`` — max results returned (default 10).
    - ``mode`` — ``hybrid`` (default) | ``semantic`` | ``keyword``.

    Returns summaries (id / title / snippet / tags), not full bodies — use
    ``GET /remote/entry/<id>`` to fetch the full content of any hit.
    """
    engine = RetrievalEngine(db, _graph)
    if not engine.resolve_identifier(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    retriever = ProgressiveRetriever(db, _graph)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results, total = retriever.search_attached(
        skill=entry_id,
        kind="heuristics",
        query=q,
        tags=tag_list,
        limit=limit,
        mode=mode,
    )
    return {
        "total_attached": total,
        "returned": len(results),
        "query": q,
        "results": [_summarize_entry(e) for e in results],
    }


@router.get(
    "/entry/{entry_id}/constraints",
    response_model=RemoteAttachedSearchResponse,
    summary="Search L4 constraints attached to an entry",
    tags=["remote"],
)
def remote_get_constraints(
    entry_id: str,
    q: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 10,
    mode: str = "hybrid",
    db: Session = Depends(get_db),
) -> dict:
    """Search the L4 constraints / failure modes attached to *entry_id*.

    Scope is restricted to nodes connected to this entry via ``constraint_on``
    or ``warning_about`` edges. Same query interface as ``/heuristics``.

    Returns summaries; fetch full content via ``GET /remote/entry/<id>``.
    """
    engine = RetrievalEngine(db, _graph)
    if not engine.resolve_identifier(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    retriever = ProgressiveRetriever(db, _graph)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results, total = retriever.search_attached(
        skill=entry_id,
        kind="constraints",
        query=q,
        tags=tag_list,
        limit=limit,
        mode=mode,
    )
    return {
        "total_attached": total,
        "returned": len(results),
        "query": q,
        "results": [_summarize_entry(e) for e in results],
    }


@router.get(
    "/entry/{entry_id}/related",
    response_model=list[dict],
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
    return [_clean_entry(e) for e in results]


@router.post(
    "/feedback",
    response_model=RemoteFeedbackResponse,
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

_INBOX_SESSION = "inbox"  # MemGraph session used for all submit() entries
_INBOX_TAG = "pending-distillation"


@router.post(
    "/submit",
    response_model=RemoteSubmitResponse,
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
            entries = mem.ingest_openai_messages(
                body.messages, tags=extra_tags, as_single_trace=True
            )
        else:
            entries = mem.ingest_autogen_messages(
                body.messages, tags=extra_tags, as_single_trace=True
            )
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
    response_model=list[RemoteInboxItem],
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
                results.append(
                    {
                        "id": e.id,
                        "session_id": e.session_id,
                        "title": (e.content.splitlines()[0].lstrip("# ") if e.content else ""),
                        "preview": e.content[:300] if e.content else "",
                        "tags": e.tags,
                        "created_at": e.created_at.isoformat(),
                        "source_format": e.source_format,
                    }
                )
    results.sort(key=lambda x: x["created_at"])
    return results[:limit]


@router.post(
    "/distill",
    response_model=RemoteDistillResponse,
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
        "was created.\n\n" + combined
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
