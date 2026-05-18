# Know-Do Graph

A wiki-native, agent-oriented infrastructure for **executable knowledge**, **operational memory**, and **capability discovery**.

Entries are the primary object — wiki pages that agents can read, traverse, and evolve.  
The graph emerges naturally from `[[wikilink]]` references between entries.

---

## Quick start

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

All commands are available via `python main.py`.

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
| `POST` | `/remote/chat` | Chat with the orchestrator agent |
| `GET` | `/remote/search` | Search entries (`?q=&tags=&entry_type=&limit=`) |
| `GET` | `/remote/graph` | Graph stats + full node/edge dump |
| `GET` | `/remote/entry/{id}` | Entry by ID, slug, or alias |
| `GET` | `/remote/entry/{id}/related` | Related entries via BFS (`?depth=1&relation=`) |
| `POST` | `/remote/feedback` | Free-form feedback trace; optionally also updates an entry's verification (pass `entry_id` + `verdict`) |
| `POST` | `/entries/{id}/feedback` | Direct per-entry verification feedback |
| `DELETE` | `/remote/session/{id}` | Clear a session's chat history |

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
produces.  Pick the adapter that matches your stack.

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
`related_workflow`, `generated_from`, `memory_of`, `refinement_of`, `derived_from`,
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
  know_do_graph.db    SQLite database (auto-created)
  memory/             Per-session JSON memory files
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

- The SQLite database is at `data/know_do_graph.db` and is created automatically on first run.
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
