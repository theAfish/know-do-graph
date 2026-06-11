# Know-Do Graph

A wiki-native, agent-oriented infrastructure for **executable knowledge**, **operational memory**, and **capability discovery**.

Entries are the primary object — wiki pages that agents can read, traverse, and evolve.  
The graph emerges naturally from `[[wikilink]]` references between entries.

---

## Quick start

### Install from PyPI

```bash
pip install know-do-graph

# Create an empty ./data/know_do_graph.db
know-do-graph init

# Or start from the database bundled with the package
know-do-graph init --starter

know-do-graph serve
```

The starter database is copied into the working location; the installed package
is never used as the writable database. Existing databases are not replaced
unless `--force` is explicitly provided.

To choose another database path, set `KDG_DB_PATH` in the environment or in a
`.env` file in the directory where the command is run:

```bash
KDG_DB_PATH=./my-data/my-memory.db
```

Relative `KDG_DB_PATH` values are resolved from the current working directory.

### Python API

Use the high-level client to embed the graph directly in an agent process:

```python
from know_do_graph import EdgeRelation, EntryType, KnowDoGraph

graph = KnowDoGraph("data/my_agent.db")

skill = graph.add(
    "Relax an atomic structure",
    entry_type=EntryType.capability,
    content="Choose a calculator, then run [[ASE Relaxation]].",
    tags=["atomistic"],
)
procedure = graph.add(
    "ASE Relaxation",
    entry_type=EntryType.procedure,
    content="Attach a calculator and run an ASE optimizer.",
)
graph.connect(skill.id, procedure.id, relation=EdgeRelation.decomposes_to)

planner_context = graph.plan("relax this crystal")
execution_context = graph.expand(skill.slug, stages=["decomposition"])

memory = graph.memory("run-42")
first = memory.add(
    "FIRE converged at fmax=0.03.",
    tags=["success"],
    success=True,
)
second = memory.add("The result reproduced with a tighter force threshold.")
memory.connect(first.id, second.id)
graph.close()
```

The main methods are `add`, `get`, `list`, `search`, `update`, `delete`,
`connect`, `related`, `plan`, `heuristics`, `constraints`, `expand`, and
`memory`. IDs, slugs, and aliases are accepted anywhere an entry identifier is
required. Each client owns its database engine, so multiple graph databases can
be used safely in the same process.

### Python chat API

Configure an OpenAI or OpenAI-compatible provider:

```bash
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://your-provider.example/v1"  # optional
export GRAPH_AGENT_MODEL="qwen-plus"                       # optional
```

Create a stateful, read-only conversation for question answering:

```python
from know_do_graph import KnowDoGraph

graph = KnowDoGraph("data/my_agent.db")
chat = graph.chat(read_only=True, model="qwen-plus")

print(chat.send("Which skills can construct a material interface?"))
print(chat.send("What constraints apply to the best candidate?"))

chat.reset()
graph.close()
```

Allow the agent to add, update, link, and retrieve graph knowledge:

```python
def on_step(event: str, data: dict) -> None:
    if event in {"tool_call", "tool_result"}:
        print(event, data)

with KnowDoGraph("data/my_agent.db") as graph:
    chat = graph.chat(model="qwen-plus", on_step=on_step)
    reply = chat.send(
        "Add a reusable capability for validating atomistic relaxations. "
        "Search for duplicates and connect it to relevant procedures."
    )
    print(reply)
```

Route a broader task through the orchestrator, or run a review batch:

```python
with KnowDoGraph("data/my_agent.db") as graph:
    orchestrator = graph.chat(agent="orchestrator", model="qwen-plus")
    print(orchestrator.send("Improve weak coverage around phonon workflows."))

    reviewer = graph.chat(agent="reviewer", model="qwen-plus", batch_size=3)
    print(reviewer.review("Focus on duplicate titles and inconsistent tags."))
```

Review raw memory separately and receive structured progress/results:

```python
def on_status(status: dict) -> None:
    print(status["status"], status["progress"])

with KnowDoGraph("data/my_agent.db") as graph:
    reviewer = graph.chat(
        agent="reviewer",
        model="qwen-plus",
        batch_size=10,
        on_status=on_status,
    )
    result = reviewer.review_memory(session_id="matcreator")
    print(result["results"], result["errors"])
```

Memory review samples only unpromoted `memory` nodes. It classifies each trace
as L1/L2/L3/L4, noise, or skip. L1/L2 become unverified capability/procedure
nodes; L3/L4 become heuristic/constraint nodes linked to an existing L1/L2
node; noise is deleted.

Applications can use the polling API instead of running reviewer logic locally:

```bash
curl -X POST http://127.0.0.1:8000/agent/review/memory \
  -H "Content-Type: application/json" \
  -d '{"session_id":"matcreator","batch_size":10}'

curl http://127.0.0.1:8000/agent/review/memory/<job-id>
```

Credentials may also be passed directly with `api_key=` and `base_url=`.
Use `graph.ask("...", read_only=True)` for a one-shot conversation.
For async applications, call `await asyncio.to_thread(chat.send, message)`.
See `examples/chat_api.py` for complete examples.

### Install from source

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 2. Install everything (Python deps + Vite frontend build)
bash install.sh

# 3. Seed example entries (optional)
python examples/example_entries.py

# 4. Start the API server
python main.py serve
# → http://127.0.0.1:8000
# → http://127.0.0.1:8000/ui   (graph browser)
# → http://127.0.0.1:8000/docs (interactive Swagger UI)
```

> **Manual frontend build** (if you prefer not to use `install.sh`):
> ```bash
> cd frontend && npm install && npm run build && cd ..
> ```
> Re-run whenever you edit files under `frontend/src/` or `frontend/styles/`.

### Release to PyPI from GitHub

This repository is set up so the Python package version comes from the Git tag
used for the release. A GitHub release published from tag `v0.1.1` will build
package version `0.1.1` and publish it to PyPI automatically.

One-time setup:

1. In PyPI, create a trusted publisher for this repository.
2. In GitHub, make sure Actions are enabled for the repository.
3. Publish releases from version tags like `v0.1.1`, `v0.2.0`, and so on.

Release flow:

```bash
git tag v0.1.1
git push origin v0.1.1
```

Then publish a GitHub release for that tag. The workflow at
`.github/workflows/release-pypi.yml` will:

1. build the frontend assets,
2. build the Python sdist and wheel,
3. publish the package to PyPI using GitHub's OIDC trusted publishing.

If you want to test the PyPI connection first, point the same workflow at
TestPyPI before using the production publisher.

### Frontend development (hot-reload)

```bash
# Terminal 1 — API backend
python main.py serve

# Terminal 2 — Vite dev server with API proxy
cd frontend && npm run dev
# → http://localhost:5173  (proxies /entries, /graph, etc. to :8000)
```

---

## CLI reference

Commands are available via `know-do-graph` after a package installation or
`python main.py` from a source checkout.

### Database initialization

```bash
# Create an empty database if one does not exist
know-do-graph init

# Copy the bundled starter database
know-do-graph init --starter

# Explicitly replace an existing database with the starter
know-do-graph init --starter --force
```

### Entry management

```bash
# Add an entry
python main.py entry add "My Tool" \
  --content "Useful for [[ASE Relaxation]]. See https://example.com" \
  --type tool \
  --tags "python,simulation" \
  --source "https://example.com"

# List entries
python main.py entry list --limit 50

# Show full entry (by ID or slug)
python main.py entry show mace-calculator
python main.py entry show 3e3f0272

# Full-text search
python main.py entry search "relaxation"

# Delete
python main.py entry delete <entry-id> --yes
```

### File extraction

```bash
# Extract from a single Markdown file
python main.py extract file notes/my_workflow.md --type workflow --tags "ase,phonon"

# Extract all .md/.txt files from a directory
python main.py extract file docs/ --type capability

# Skip automatic wikilink resolution
python main.py extract file notes/ --no-resolve
```

### Graph inspection

```bash
python main.py graph stats
python main.py graph neighbors <entry-id> --depth 2
python main.py graph export --output data/nodes   # writes YAML files
```

### Memory (Mem-Graph)

```bash
# Record a trace manually
python main.py mem add "MACE calculator worked for bulk Fe relaxation" \
  --session my-session --tags "success,atomistic"

# List traces for a session
python main.py mem list --session my-session

# Promote a trace into a full KDG entry
python main.py mem promote <mem-id> --session my-session --type capability
```

### Start the server

```bash
python main.py serve                          # default: 127.0.0.1:8000
python main.py serve --host 0.0.0.0 --port 9000 --reload
```

The CLI prints clickable URLs on startup:

```
Know-Do Graph API  →  http://127.0.0.1:8000
  Graph UI         →  http://127.0.0.1:8000/ui
  Swagger          →  http://127.0.0.1:8000/docs
```

---

## Graph Debugger UI

A built-in browser frontend for visualising and debugging the graph is served at **`/ui`**.

| Feature | Details |
|---------|---------|
| Force-directed layout | Nodes sized by degree, coloured by entry type |
| **Hover** | Tooltip with name, type, slug, refinement status, trust score, tags |
| **Click** | Side panel with full entry detail: content, wikilinks, all metadata, connected edges |
| Search & filter | Live search by title/slug; filter by entry type |
| Labels toggle | Show/hide node title labels |
| Click edge targets | Jump directly to a connected node from the detail panel |

Open it at `http://127.0.0.1:8000/ui` while the server is running.

---

## API reference

Interactive docs at `http://127.0.0.1:8000/docs` once the server is running.

### Entries

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/entries/` | List entries (paginated) |
| `GET` | `/entries/search?q=...&tags=...&entry_type=...` | Full-text search |
| `GET` | `/entries/{id}` | Get entry by ID or slug |
| `POST` | `/entries/` | Create entry |
| `PUT` | `/entries/{id}` | Update entry |
| `DELETE` | `/entries/{id}` | Delete entry |
| `GET` | `/entries/{id}/related?depth=1&relation=...` | Traverse related entries |
| `GET` | `/entries/{id}/edges` | All edges incident to an entry |
| `GET` | `/entries/{id}/download` | Download script content (entries with `script_language` set) |
| `POST` | `/entries/{id}/feedback` | Record verification feedback (works / bugged / …) |

### Graph

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/graph/stats` | Node/edge counts |
| `GET` | `/graph/full` | All nodes and edges (used by the UI) |
| `GET` | `/graph/neighbors/{id}?direction=both` | Immediate neighbors |
| `GET` | `/graph/subgraph/{id}?depth=2` | Ego-subgraph |
| `GET` | `/graph/path?source=...&target=...` | All simple paths between two entries |

### Memory (Mem-Graph)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mem/sessions` | List all session IDs |
| `GET` | `/mem/{session}` | List traces for a session |
| `POST` | `/mem/{session}/add` | Add a plain-text trace |
| `POST` | `/mem/{session}/ingest/openai` | Ingest OpenAI chat messages |
| `POST` | `/mem/{session}/ingest/langchain` | Ingest LangChain messages |
| `POST` | `/mem/{session}/ingest/autogen` | Ingest AutoGen conversation |
| `POST` | `/mem/{session}/ingest/raw` | Ingest arbitrary JSON |
| `DELETE` | `/mem/{session}/{mem_id}` | Delete a trace |
| `POST` | `/mem/{session}/{mem_id}/promote` | Promote trace → KDG entry |

### Progressive retrieval (hierarchical memory)

The graph is organised into four orthogonal **skill levels** so planning
context stays small and operational details are pulled on demand.

| Level | Stored as | Purpose |
|-------|-----------|---------|
| **L1 — Capability** | `entry_type` ∈ {`capability`, `workflow`} | Reusable high-level abilities (planner-facing) |
| **L2 — Procedure**  | `entry_type` = `procedure` | Executable workflow decomposition |
| **L3 — Heuristic**  | `entry_type` = `heuristic` | Empirical, conditional guidance (cooling rate ⇒ sp2/sp3 ratio, …) |
| **L4 — Constraint** | `entry_type` = `constraint` | Known failure modes / instability regions |

`EntryMetadata.skill_level` may override the level explicitly. New typed edges
wire the layers together:

- `decomposes_to` (L1 → L2)
- `heuristic_for` (L3 → L1/L2)
- `constraint_on` (L4 → L1/L2)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/retrieve/plan?goal=…&k=5&include_l2=true` | L1 (+ L2) candidates for a goal — planner context |
| `GET` | `/retrieve/heuristics?skill=<id\|slug>&k=5` | L3 heuristics attached to a skill (fallback: semantic) |
| `GET` | `/retrieve/constraints?skill=<id\|slug>&k=5` | L4 constraints / failure modes (fallback: semantic) |
| `GET` | `/retrieve/expand/{skill}?stages=heuristics,constraints,decomposition` | Bundle used by verifier / debugging loops |

Recommended flow::

    goal → /retrieve/plan
         → pick skill, execute
         → on verifier feedback or uncertainty
         → /retrieve/heuristics  +  /retrieve/constraints
         → refinement / debugging

GraphAgent exposes the same staging as tools (`retrieve_plan`,
`retrieve_heuristics`, `retrieve_constraints`) plus `create_heuristic`,
`create_constraint`, and `decompose_capability` so it can grow the L3/L4
layer instead of dumping operational knowledge into capability content.

To migrate an existing graph:

```bash
python scripts/backfill_skill_levels.py --dry-run   # preview
python scripts/backfill_skill_levels.py             # apply
```

---

## Node verification & self-evolution

Every entry carries metadata that lets the graph evolve from raw scraped notes
into a trusted capability library:

| Field | Purpose |
|-------|---------|
| `verification_status` | `unverified` (default) → `self_tested` / `peer_reviewed` / `community_tested` / `bugged` / `deprecated` |
| `feedback_log` | Append-only list of `{timestamp, agent_id, verdict, note, evidence}` |
| `needs_generalization` | Set automatically when `create_entry` detects an overly specific title (e.g. `Build H2O`) overlapping an existing generic node |
| `review_count` / `modify_count` | Incremented by `ReviewAgent` |
| `trust_score` / `usage_count` | Reserved for downstream ranking |

External agents that **execute** a skill should immediately report the outcome
via `POST /entries/{id}/feedback` (verdict `works` or `bugged`). The
`MaintenanceAgent` regularly sweeps for `unverified`, `bugged`, and
`needs_generalization` entries and proposes fixes; the `GraphAgent` exposes
`submit_feedback`, `list_by_verification`, and `list_needs_generalization`
tools so an LLM can do the same.

### Abstraction guard

`create_entry` runs a heuristic that flags titles containing concrete
chemical formulas (`H2O`, `TiO2`, `TiO2/SrTiO3`) and any title that overlaps
an existing one. The new entry is still created, but with
`metadata.needs_generalization = True` so it surfaces in maintenance sweeps.
The agent system prompt gives BAD/GOOD examples — prefer
**`Build molecule from formula`** over **`Build H2O`**, and
**`Material interface construction`** over **`TiO2/SrTiO3 Interface`**.

`build_material_interface_workflow` is now deprecated for this reason and
returns an error explaining the generic alternative.

---

## Remote agent access

The server exposes a dedicated `/remote` interface so that agents running on
other machines can discover, query, and interact with the graph over plain HTTP
— no special client library required.

### Discovery: the instruction sheet

When any client hits the server root (or `/remote`), it receives a plain-text
instruction sheet explaining every available endpoint, request formats, and
example `curl` commands:

```bash
curl http://<host>:<port>/
# or
curl http://<host>:<port>/remote
```

### Remote agent endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Instruction sheet (plain text) |
| `GET` | `/remote` | Same instruction sheet |
| `POST` | `/remote/chat` | Chat with the orchestrator agent (read-only; agents and humans) |
| `GET` | `/remote/search` | Search entries (`?q=&tags=&entry_type=&limit=`) |
| `GET` | `/remote/graph` | Graph stats + full node/edge dump |
| `GET` | `/remote/entry/{id}` | Entry by ID, slug, or alias |
| `GET` | `/remote/entry/{id}/related` | Related entries via BFS (`?depth=1&relation=`) |
| `POST` | `/remote/feedback` | Free-form feedback trace; optionally also updates an entry's verification (pass `entry_id` + `verdict`) |
| `POST` | `/entries/{id}/feedback` | Direct per-entry verification feedback |
| `DELETE` | `/remote/session/{id}` | Clear a session's chat history |
| `POST` | `/remote/submit` | Deposit raw knowledge into the inbox (agents and humans) |
| `GET` | `/remote/inbox` | List pending inbox submissions awaiting distillation (humans) |
| `POST` | `/remote/distill` | Run graph agent to convert inbox into proper nodes (humans) |

### Chat (one-shot)

```bash
curl -X POST http://<host>:<port>/remote/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "What entries exist in the graph?"}'
```

```json
{"response": "The graph currently contains ...", "session_id": "a1b2c3..."}
```

### Chat (multi-turn)

Pass a stable `session_id` to retain conversation history across calls:

```bash
# Turn 1
curl -X POST http://<host>:<port>/remote/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "List all procedure entries", "session_id": "agent-42"}'

# Turn 2 — the server remembers the context from turn 1
curl -X POST http://<host>:<port>/remote/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Now show the dependencies of the first one", "session_id": "agent-42"}'

# Clear history when done
curl -X DELETE http://<host>:<port>/remote/session/agent-42
```

### Search

```bash
# Free-text search
curl "http://<host>:<port>/remote/search?q=relaxation&limit=5"

# Filter by type
curl "http://<host>:<port>/remote/search?entry_type=tool"

# Combined: text + tags
curl "http://<host>:<port>/remote/search?q=ase&tags=python,simulation"
```

### Feedback / observations

There are **two complementary feedback channels**:

**(a) Per-entry verification feedback** — updates the entry's
`verification_status` (one of `unverified`, `self_tested`, `peer_reviewed`,
`community_tested`, `bugged`, `deprecated`) and appends to its `feedback_log`.
This is how the graph self-evolves — a node that an external agent has run
and confirmed working will be trusted higher next time.

```bash
# Verdicts: works | peer_works | bugged | deprecated | unclear
curl -X POST http://<host>:<port>/entries/<id-or-slug>/feedback \
     -H "Content-Type: application/json" \
     -d '{
       "verdict": "works",
       "note": "Ran on H2O, energy converged in 12 steps",
       "evidence": "log link or excerpt",
       "agent_id": "matcreator-runner-1"
     }'
```

**(b) Free-form session feedback** — stored as a MemGraph trace; can later be
promoted to a full entry. Optionally also routes to (a) when you pass
`entry_id` and `verdict`:

```bash
curl -X POST http://<host>:<port>/remote/feedback \
     -H "Content-Type: application/json" \
     -d '{
       "session_id": "agent-42",
       "content": "MACE relaxation diverged on Cu surfaces",
       "tags": ["feedback", "graph-quality"],
       "entry_id": "mace-relaxation",
       "verdict": "bugged",
       "agent_id": "matcreator-runner-1"
     }'
```

The `MaintenanceAgent` exposes `list_unverified()`, `list_bugged()`, and
`list_needs_generalization()` so it can sweep for entries needing attention.

Promote feedback traces to entries via `POST /mem/{session_id}/{mem_id}/promote`.

### Knowledge inbox (submit → review → distill)

External agents — and humans — can deposit raw knowledge into an **inbox** for
later review and distillation into proper graph nodes.  Nothing touches the
graph until you explicitly trigger distillation, so you stay in control of what
gets added.

**Step 1 — Submit** (agents or humans)

```bash
# Plain-text summary or context dump
curl -X POST http://<host>:<port>/remote/submit \
     -H "Content-Type: application/json" \
     -d '{
       "title": "MACE geometry optimisation walkthrough",
       "content": "We used MACE-MP-0 to relax a bulk Fe structure ...",
       "tags": ["mace", "relaxation"],
       "agent_id": "matcreator-01"
     }'

# OpenAI-style conversation transcript
curl -X POST http://<host>:<port>/remote/submit \
     -H "Content-Type: application/json" \
     -d '{
       "title": "ASE relaxation session",
       "format": "openai",
       "messages": [
         {"role": "user",      "content": "How do I relax a structure with ASE?"},
         {"role": "assistant", "content": "Use BFGS with an Atoms object ..."}
       ],
       "agent_id": "matcreator-01"
     }'
```

The submission is stored as a memory trace tagged `pending-distillation` and
returns the entry `id` for reference.

**Step 2 — Review the inbox** (humans)

```bash
curl http://<host>:<port>/remote/inbox
# → list of pending submissions with a 300-char preview each

# Scope to a specific agent's session
curl "http://<host>:<port>/remote/inbox?session_id=matcreator-01"
```

**Step 3 — Distill** (humans, when ready)

```bash
# Process all pending submissions and create graph nodes
curl -X POST http://<host>:<port>/remote/distill \
     -H "Content-Type: application/json" \
     -d '{}'

# Preview what the agent would receive without touching the graph
curl -X POST http://<host>:<port>/remote/distill \
     -H "Content-Type: application/json" \
     -d '{"dry_run": true}'

# Distil only one agent's submissions
curl -X POST http://<host>:<port>/remote/distill \
     -H "Content-Type: application/json" \
     -d '{"session_id": "matcreator-01"}'
```

The graph agent reads every pending submission, extracts reusable
capabilities/procedures/tools (following the abstraction rules), and marks the
inbox entries as promoted so they are not processed again.

### Starting the server for remote access

```bash
# Expose on all interfaces so other machines can connect:
python main.py serve --host 0.0.0.0 --port 8000

# With auto-reload during development:
python main.py serve --host 0.0.0.0 --port 8000 --reload
```

Set `OPENAI_API_KEY` (and optionally `OPENAI_API_BASE`) before starting if you
want the `/remote/chat` endpoint to work.

---

## Connecting agent frameworks

MemGraph accepts session data in whichever format the agent framework already
produces. Memory traces are stored in the same SQLite database as all other
nodes with `entry_type="memory"`. Session and ingestion details are retained in
entry metadata, and memory nodes can be connected with normal graph edges.
Pick the adapter that matches your stack.

### OpenAI / OpenAI-compatible APIs

```python
from core.memory.memgraph import MemGraph

response = openai_client.chat.completions.create(...)
messages = [m.model_dump() for m in response.choices[0].message]  # or your history list

mg = MemGraph("my-session")
mg.ingest_openai_messages(messages, tags=["openai", "physics-qa"])
```

Or via the API:

```bash
curl -X POST http://localhost:8000/mem/my-session/ingest/openai \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}'
```

### LangChain

```python
from core.memory.memgraph import MemGraph

# chain.memory.chat_memory.messages → list of HumanMessage / AIMessage objects
mg = MemGraph("langchain-session")
mg.ingest_langchain_messages(chain.memory.chat_memory.messages)
```

Objects only need a `.content` attribute (and optionally `.type` / `.role`).

### AutoGen

```python
from core.memory.memgraph import MemGraph

# groupchat.messages → list of {"name": "...", "content": "...", "role": "..."}
mg = MemGraph("autogen-session")
mg.ingest_autogen_messages(groupchat.messages, tags=["autogen", "multi-agent"])
```

### JSON session dump

```python
from pathlib import Path
from core.memory.memgraph import MemGraph

mg = MemGraph("dump-session")
mg.ingest_file(Path("session_export.json"))
```

Accepted JSON shapes:
- A **JSON array** → treated as an OpenAI/AutoGen message list
- A **JSON object** with a `messages`, `history`, `conversation`, or `turns` key → that list is extracted
- Anything else → stored as a single serialised trace

### Plain text / log file

```python
from pathlib import Path
from core.memory.memgraph import MemGraph

mg = MemGraph("log-session")
mg.ingest_text_file(Path("agent.log"), chunk_by="paragraph")
# chunk_by options: "none" | "line" | "paragraph"
```

### Direct `add()` (any framework)

```python
mg = MemGraph("custom-session")
mg.add(
    "Summarised finding from the session: ...",
    tags=["finding", "success"],
    success=True,
)
```

---

## Entry format and wikilinks

Entries are wiki-style documents.  Internal `[[wikilinks]]` automatically
create graph edges when you call `resolve_wikilinks()` or use the
`--resolve` flag during extraction.

```markdown
# ASE Relaxation

Geometry optimisation workflow using [[ASE]].

## Prerequisites
- [[ASE]]
- A [[MACE Calculator]] or other calculator

## Related
- [[Phonon Workflow]]
```

Supported `entry_type` values: `capability`, `procedure`, `workflow`, `tool`,
`repository`, `environment`, `dependency`, `data`, `analytical`, `memory`, `generic`.

Supported edge `relation` values: `dependency`, `compatible_with`, `alternative_to`,
`related_workflow`, `generated_from`, `memory_of`, `related_memory`, `refinement_of`, `derived_from`,
`warning_about`, `cited_by`, `wikilink`, `prerequisite`, `replacement`,
`execution_pathway`, `transformation`, `provenance`, `compatibility`.

---

## Project structure

```
core/
  schemas/        Pydantic models — Entry, EntryMetadata, Edge, enums
  graph/          KnowDoGraph (networkx wrapper) + app_state singleton
  storage/        SQLAlchemy/SQLite models, DB session, repositories
  retrieval/      RetrievalEngine — search, traversal
  extraction/     Wikilink parser, external-ref extractor
  memory/         MemGraph — session memory traces + ingestion adapters

agents/
  extraction_agent/   File/text → entries + wikilink resolution
  maintenance_agent/  Graph rebuild, dangling-edge cleanup, YAML export, promotion

api/
  main.py             FastAPI application
  routes/
    entries.py        CRUD + search + traversal endpoints
    graph.py          Stats, subgraph, path-finding endpoints
    mem.py            Mem-Graph ingestion + management endpoints
    remote.py         Remote agent access + instruction sheet endpoints

data/
  know_do_graph.db    Default working SQLite database
  memory/             Legacy JSON memory files (imported into SQLite on first access)
  nodes/              YAML entry exports (via `graph export`)

examples/
  example_entries.py  Seed script with 5 cross-linked atomistic entries

main.py             Typer CLI entry point
requirements.txt    Python dependencies
```

---

## Mem-Graph → Know-Do Graph promotion

Memory traces are shallow and mutable.  When a trace represents a stable,
reusable insight, promote it:

```bash
# CLI
python main.py mem promote <mem-id> --session my-session --type capability

# API
curl -X POST http://localhost:8000/mem/my-session/<mem-id>/promote \
  -H "Content-Type: application/json" \
  -d '{"entry_type": "capability", "tags": ["promoted"]}'
```

The promotion pathway:

```
raw mem trace  →  linked note  →  refined capability entry  →  validated knowledge
```

---

## Development notes

- The default SQLite database is `./data/know_do_graph.db`, relative to the
  directory where the process is started.
- Set `KDG_DB_PATH` to configure a different filename or path.
- `init` creates an empty database; `init --starter` copies the bundled starter
  database to the working path.
- To package the current development database as the next starter, stop the API
  server and run:

  ```bash
  ./scripts/build_starter.sh
  ```

  The script checkpoints `data/know_do_graph.db`, copies it to the tracked
  release snapshot at `assets/starter.db`, builds the source distribution and
  wheel into `dist/`, and verifies that the wheel contains the complete starter
  database. The live database under `data/` is ignored by Git.
- The in-memory networkx graph is rebuilt from the database on every server startup (or via `MaintenanceAgent.rebuild_graph()`).
- All timestamps are UTC.
- Vector indexing and heavyweight graph databases are intentionally deferred — the architecture supports adding them later without structural changes.

---

## Agent web access

The `GraphAgent` has two complementary web tools:

| Tool | How it works | When to use |
|------|-------------|-------------|
| `web_search` | DuckDuckGo search API, returns titles + snippets | Discovering URLs, broad topic research |
| `fetch_url` | HTTP GET via `httpx` (or stdlib fallback), returns up to 20 000 chars of page text | Reading a specific URL the user provides, scraping docs/READMEs |

**`fetch_url` requires `httpx`** (already in `requirements.txt` if you're using the API server).  
It falls back to `urllib` automatically if `httpx` is not installed.

Example agent usage:

```
You: fetch https://ase.readthedocs.io/en/latest/ and create a tool entry for ASE
Agent: [calls fetch_url → reads page → calls create_entry]
```
