---

# Refactoring and Standardization Backlog

This backlog is based on the current repository shape and should be treated as
developer-experience work before the next major feature push. The goal is to
make the code easier to navigate, safer to change, and more consistent across
the CLI, API, agents, storage layer, and frontend.

## Priority 1 - Establish Project Conventions

- [x] Add a short `CONTRIBUTING.md` with local setup, test commands, lint/type-check commands, coding style, and release/build notes.
- [x] Decide one supported Python floor and make it consistent everywhere. `README.md` says Python 3.11+, while `pyproject.toml` allows `>=3.10` and Ruff/Mypy target 3.10.
- [x] Add standard developer scripts or documented commands for:
  - [x] Python tests: `pytest` or `python -m unittest`
  - [x] Python lint: `ruff check .`
  - [x] Python format: `ruff format .` or an explicit alternative
  - [x] Python typing: `mypy`
  - [x] Frontend build: `npm --prefix frontend run build`
- [x] Add CI checks in `.github/` for Python tests, linting, type checking, and frontend build.
- [x] Add an `.editorconfig` so indentation, line endings, final newline, and charset are consistent across Python, JS, CSS, Markdown, and TOML files.
- [x] Remove committed generated/cache files such as `__pycache__/` and make sure `.gitignore` covers Python caches, frontend build artifacts, local databases, local virtualenvs, and environment files.
- [x] Audit text encoding in docs and source comments. Several files display mojibake characters, so normalize files to UTF-8 and replace corrupted punctuation/box drawing where it affects readability.

## Priority 2 - Split Oversized Modules

- [x] Break the root CLI in `main.py` into a package such as `know_do_graph.cli`.
  Suggested modules:
  - [x] `cli/app.py` for Typer app creation
  - [x] `cli/entries.py`
  - [x] `cli/graph.py`
  - [x] `cli/memory.py`
  - [x] `cli/agents.py`
  - [x] `cli/db.py`
  - [x] `cli/serve.py`
- [x] Keep `main.py` as a thin compatibility wrapper, then update `pyproject.toml` script entry point away from `main:app` once imports are stable.
- [x] Split `agents/graph_agent/tools.py` by capability area. It currently combines CRUD, search, web access, scripts/assets, material helpers, sidecars, retrieval, and tool schemas.
  Suggested modules:
  - [x] `tools/entries.py`
  - [x] `tools/edges.py`
  - [x] `tools/retrieval.py`
  - [x] `tools/assets.py`
  - [x] `tools/feedback.py`
  - [x] `tools/web.py`
  - [x] `tools/materials.py`
  - [x] `tools/registry.py`
- [x] Split `agents/review_agent/tools.py` into sampling, inspection, mutation, distillation, merge, memory-review, and registry modules.
- [x] Split `api/routes/remote.py` into chat/session routes, graph/search routes, feedback routes, inbox/distillation routes, and instruction rendering.
- [x] Split `core/memory/memgraph.py` into storage/session operations, ingest adapters, conversion helpers, and promotion logic.
- [x] Split `frontend/src/ui/panel.js` into detail rendering, edit form, assets/scripts rendering, metadata rendering, and event handlers.

Implementation note: these splits preserve compatibility by moving the prior large
implementations behind package facades (`*_legacy.py` modules) and exposing
smaller category modules. Priority 3 can now move shared service logic out of
the legacy modules incrementally without breaking public import paths.

## Priority 3 - Clarify Boundaries and Shared Services

- [x] Create service-layer modules for repeated workflows that are currently implemented separately in CLI, API routes, agent tools, and `KnowDoGraph` client methods.
  Candidates:
  - [x] entry create/update/delete
  - [x] edge create/delete
  - [x] asset/script mutation
  - [x] feedback and verification updates
  - [x] graph reload and SSE notification
  - [x] memory promotion
- [x] Move slug generation to one canonical implementation. There are separate slug helpers in `core/storage/repository.py`, `core/extraction/wikilink_parser.py`, `core/schemas/entry.py`, and `agents/graph_agent/tools.py`.
- [x] Centralize serialization helpers for entry summaries, clean remote responses, API response models, and frontend graph node payloads.
- [x] Replace direct access to graph internals such as `g._g.degree()` with public graph methods.
- [x] Replace broad `Any` usage in agent/review/public API boundaries with `Protocol`, typed context objects, or concrete service interfaces.
- [x] Standardize error handling. Decide where functions return `{"error": ...}` versus raising domain exceptions, then adapt API routes and agents consistently.
- [x] Standardize event emission so repositories, API routes, and services do not double-emit or emit slightly different payloads for the same mutation.

Implementation note: shared services now live under `core/services`, canonical
slug generation lives in `core/utils/slug.py`, API/client/GraphAgent hot paths
use service-layer mutations, and graph degree/full-dump access goes through
public methods. Some legacy `Any` annotations remain in agent tool-call
interfaces for OpenAI compatibility; those should be narrowed during the
Priority 6 agent-tooling pass.

## Priority 4 - Improve Persistence and Migrations

- [x] Replace ad hoc SQLite migrations in `core/storage/database.py` with a small migration system or Alembic.
- [x] Add migration tests for fresh databases and older starter databases.
- [x] Define indexes explicitly for common lookups: slug, aliases if supported, entry type, verification status, timestamps, and edge source/target.
- [x] Review transaction boundaries in repository methods. Avoid committing multiple times inside a single high-level operation unless the behavior is intentional.
- [x] Make embedding refresh an explicit post-commit service or background job so write operations are easier to reason about and test.
- [x] Add a database config object instead of relying on module-level `DB_PATH`, `engine`, and `SessionLocal` in new code.

Implementation note: database migrations now live in `core/storage/migrations.py`,
database path resolution lives in `core/storage/config.py`, and embedding refresh
is isolated in `core/services/embeddings.py`. Repository writes still preserve
the existing commit semantics, but the secondary embedding update is now a
named post-commit operation and covered by the broader validation suite.

## Priority 5 - Strengthen API Contracts

- [x] Add Pydantic request/response models for all FastAPI routes instead of returning untyped `dict` and `list[dict]` from most endpoints.
- [x] Add pagination metadata for list/search endpoints rather than only `limit` and `offset`.
- [x] Standardize identifier handling across API routes. Some routes accept ID/slug/alias, but names such as `entry_id` do not always make that clear.
- [x] Extract the long remote instruction text from `api/routes/remote.py` into a template file or docs module.
- [x] Add API tests for entry CRUD, assets/scripts, remote search, remote feedback, memory routes, and graph reload/events.
- [x] Add compatibility tests for the public Python client, CLI, and REST API doing the same lifecycle operations.

Implementation note: API contracts now live in `api/schemas.py`, with typed
response models across entry, graph, progressive retrieval, memory, remote-sync,
agent, and remote agent routes. List/search style endpoints return pagination
envelopes where appropriate, remote instructions render from
`api/routes/remote_instructions.py`, and `tests/test_api_contracts.py` covers
route shapes plus REST, public client, and CLI lifecycle compatibility.

## Priority 6 - Improve Agent Tooling Architecture

- [x] Introduce a tool registry abstraction instead of building large module-level dispatch dictionaries by hand.
- [x] Separate tool implementation from OpenAI function/tool schema definitions.
- [x] Add unit tests for each mutating tool with an isolated temporary database.
- [x] Add read-only enforcement tests for `GraphAgent` to ensure mutating tools cannot be called in read-only mode.
- [x] Add policy enforcement tests for `ReviewAgent` protected statuses, excluded types, and allowed actions.
- [x] Normalize agent tool return shapes so callers can reliably inspect success, errors, IDs, and changed fields.
- [x] Move network-capable tools such as `fetch_url` and `web_search` behind an explicit capability/config flag.

Implementation note: shared agent tooling now lives in `agents/tooling.py`.
Graph and review agents expose `ToolRegistry` instances from their respective
`tools/registry.py` modules, use normalized `ok`/`error` result envelopes for
dict-shaped tool calls, and hide `fetch_url`/`web_search` unless
`KDG_ENABLE_NETWORK_TOOLS=1` is set. `tests/test_agent_tooling.py` covers all
graph mutating tools against temporary databases plus read-only and review
policy enforcement paths.

## Priority 7 - Frontend Standardization

- [x] Add frontend linting and formatting, for example ESLint plus Prettier or Biome.
- [x] Add TypeScript or JSDoc typedefs for API payloads, graph nodes, edges, entries, metadata, assets, and UI state.
- [x] Centralize DOM query helpers and avoid silent failures when required elements are missing.
- [x] Replace inline `onclick` handlers generated by `panel.js` with delegated event handlers and `data-*` attributes.
- [x] Add a small API client contract test or mocked frontend test for graph loading, panel rendering, edit submit, delete, search, and SSE refresh.
- [x] Split CSS by responsibility and document naming conventions. Current files are separated by broad area, but component ownership is still implicit.
- [x] Add accessible labels, keyboard behavior checks, and focus management tests for the detail panel, toolbar, search, and dialogs.

Implementation note: frontend scripts now include ESLint, Prettier, and Vitest
gates. JSDoc contracts live in `frontend/src/types.js`, required DOM access is
centralized in `frontend/src/dom.js`, and the detail panel uses delegated
`data-action` handlers instead of inline callbacks. `frontend/tests` covers API
payload handling, panel render/edit/delete flows, search filtering/API search,
and SSE refresh signaling. CSS ownership is documented in
`frontend/styles/README.md`.

## Priority 8 - Documentation Cleanup

- [ ] Keep `README.md` focused on installation, quick start, API examples, and links to deeper docs.
- [ ] Move architecture details into `docs/architecture.md`.
- [ ] Move API route examples into `docs/api.md`.
- [ ] Move agent behavior and tool descriptions into `docs/agents.md`.
- [ ] Move memory/progressive retrieval design into `docs/memory-and-retrieval.md`.
- [ ] Move long-term product vision out of `todo.md` into `docs/roadmap.md`, then keep `todo.md` as an actionable backlog.
- [ ] Add a module map that explains `core/`, `api/`, `agents/`, `know_do_graph/`, `frontend/`, `examples/`, and `tests/`.

## Priority 9 - Testing Gaps

- [ ] Add focused tests around slug uniqueness and alias resolution.
- [ ] Add tests for wikilink parsing and autolinking edge cases.
- [ ] Add tests for delete behavior to confirm entries, incident edges, vector rows, in-memory graph state, and emitted events stay consistent.
- [ ] Add tests for embedding-provider fallback paths so keyword retrieval remains reliable when embeddings are unavailable.
- [ ] Add tests for database merge/dedup dry-run and apply behavior.
- [ ] Add tests for remote sync parsing, due checks, successful sync, and failure metadata.
- [ ] Add frontend build verification to CI.

## Priority 10 - Packaging and Release Hygiene

- [ ] Confirm package data paths for `assets/starter.db` and `frontend/dist` work from both editable installs and built wheels.
- [ ] Decide whether `examples` should ship in the wheel or only in source distributions.
- [ ] Add release checklist covering version source, frontend build, starter DB inclusion, smoke tests, and PyPI publishing.
- [ ] Add a smoke test that installs the built wheel into a clean environment and runs `know-do-graph init`, `know-do-graph serve --help`, and a minimal Python client lifecycle.
