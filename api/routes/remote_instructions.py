"""Remote agent instruction rendering."""

from __future__ import annotations

import textwrap

from fastapi import Request

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

    # Progressive disclosure — when an entry has attached L3/L4 sidecar
    # nodes, the entry response includes a `progressive_hints` block. These
    # endpoints behave like /remote/search but are scoped to the L3/L4
    # nodes attached to the watched entry. Returns summaries — fetch full
    # content via /remote/entry/<id>:
    curl "http://{host}/remote/entry/<id>/heuristics?q=keywords&limit=10"
    curl "http://{host}/remote/entry/<id>/constraints?q=keywords&limit=10"

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
    GET  /remote/entry/{{id}}/heuristics  — Attached L3 heuristics (experience); scoped search, supports q/tags/limit
    GET  /remote/entry/{{id}}/constraints — Attached L4 constraints (limits); scoped search, supports q/tags/limit
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

      Search returns a compact summary per entry — id, title, slug,
      entry_type, tags, aliases, and a short content snippet. Use
      GET /remote/entry/<id-or-slug> to fetch the full content of any
      hit you want to inspect.

    ═══ NOTES ═══════════════════════════════════════════════════════════

      • For full CRUD access use /entries, /graph, /mem, and /agent routes.
      • Human-readable graph explorer:  http://{host}/ui
      • Full API reference:             http://{host}/docs
    """
)


def render_remote_instructions(host: str) -> str:
    return _INSTRUCTIONS_TEMPLATE.format(host=host)


def _render_instructions(request: Request) -> str:
    host = request.headers.get("host", "localhost:8000")
    return render_remote_instructions(host)
