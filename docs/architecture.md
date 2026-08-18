# Architecture

Know-Do Graph is organized around a durable SQLite-backed knowledge graph, a
Python client, a FastAPI server, agent wrappers, and a browser debugger.

## Core Concepts

- **Entry**: the primary knowledge object. Entries are wiki-style pages with
  typed metadata, tags, aliases, assets, scripts, and verification state.
- **Edge**: a typed relationship between entries, such as `dependency`,
  `decomposes_to`, `heuristic_for`, `constraint_on`, or `wikilink`.
- **Memory trace**: raw operational memory stored as `entry_type="memory"` and
  later promoted or distilled into stable graph entries.
- **Progressive retrieval**: staged retrieval that first returns high-level
  capabilities/procedures, then pulls heuristics and constraints only when
  needed.

## Runtime Shape

```text
FastAPI routes / CLI / agents / Python client
        |
core services
        |
repositories + retrieval + memory graph
        |
SQLite database + in-memory NetworkX graph
```

The database is authoritative. The in-memory NetworkX graph is rebuilt from the
database at startup and refreshed after mutations.

## Shared Services

Reusable workflows live under `core/services` so CLI commands, API routes,
public client methods, and agent tools share the same mutation and serialization
behavior. This keeps entry CRUD, edge changes, assets/scripts, feedback,
memory promotion, graph reload, and event emission consistent.

## Persistence

Storage lives under `core/storage`:

- `database.py`: engine/session plumbing and migration bootstrap.
- `migrations.py`: small ordered SQLite migration runner.
- `models.py`: SQLAlchemy tables.
- `repository.py`: entry/edge persistence operations.
- `config.py`: database path resolution from `KDG_DB_PATH`.

Common lookups are indexed for slugs, entry types, verification status,
timestamps, and edge source/target columns.

## Retrieval

`core/retrieval` combines keyword search, optional vector search, reciprocal
rank fusion, graph traversal, and progressive retrieval helpers. Embeddings are
optional; keyword retrieval remains the reliable fallback when no embedding
provider is configured.

## Agents

Agent wrappers live under `agents/`. `GraphAgent` and `ReviewAgent` expose
OpenAI-compatible tool schemas through registries. Tool results use a consistent
`ok`/`error` envelope for dict-shaped mutation results, and network tools are
disabled unless `KDG_ENABLE_NETWORK_TOOLS=1` is set.

## Frontend

The browser debugger is a Vite application under `frontend/`. It talks to the
same REST API as external clients, renders `/graph/full`, and listens to the
graph SSE stream for refresh hints.

## Verification and Self-Evolution

Entries carry verification metadata:

- `verification_status`: `unverified`, `self_tested`, `peer_reviewed`,
  `community_tested`, `bugged`, or `deprecated`.
- `feedback_log`: append-only execution or review observations.
- `needs_generalization`: flag for overly specific concepts.
- `review_count` and `modify_count`: review activity counters.

External executors should report results through feedback endpoints so the
graph can rank trusted skills higher over time.
