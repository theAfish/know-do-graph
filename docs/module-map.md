# Module Map

## `core/`

Domain, persistence, retrieval, memory, and service-layer code.

- `core/schemas`: Pydantic models and enums for entries, edges, assets, and metadata.
- `core/graph`: in-memory graph wrapper and graph-level public operations.
- `core/storage`: SQLAlchemy models, sessions, repositories, config, and migrations.
- `core/services`: shared mutation, serialization, feedback, memory, and graph-sync workflows.
- `core/retrieval`: keyword/vector retrieval, fusion, and progressive retrieval.
- `core/extraction`: wikilink parsing and reference extraction.
- `core/memory`: memory trace storage, ingestion adapters, and promotion helpers.
- `core/sync`: database merge/dedup support.
- `core/utils`: small shared helpers such as canonical slug generation.

## `api/`

FastAPI application and route contracts.

- `api/main.py`: app creation and route registration.
- `api/schemas.py`: request/response models for HTTP boundaries.
- `api/routes/entries.py`: entry CRUD, search, related entries, assets, scripts, and feedback.
- `api/routes/graph.py`: graph stats, full graph payload, paths, subgraphs, and SSE events.
- `api/routes/mem.py`: memory sessions, ingestion, and promotion.
- `api/routes/agent.py`: local agent and review-job endpoints.
- `api/routes/remote*`: remote agent instruction sheet, chat, search, graph, inbox, and distillation endpoints.

## `agents/`

LLM-facing workflows.

- `agents/graph_agent`: graph-editing and read-only query assistant.
- `agents/review_agent`: incremental quality review and memory distillation.
- `agents/orchestrator_agent`: broader task routing.
- `agents/extraction_agent`: file/text extraction and wikilink resolution.
- `agents/maintenance_agent`: rebuilds, cleanup, and graph maintenance tasks.
- `agents/tooling.py`: shared tool registry and result-normalization helpers.

## `know_do_graph/`

Public Python package surface.

- `client.py`: high-level `KnowDoGraph` client.
- `chat.py`: chat/review/orchestrator facades.
- `review.py`: review policy types.
- `cli/`: Typer command groups for entries, graph, memory, agents, DB, and serving.

## `frontend/`

Vite graph debugger UI.

- `src/api.js`: browser API client.
- `src/graph`: D3 rendering, interactions, and coloring.
- `src/ui`: toolbar, search, legend, tooltip, shortcuts, and detail panel.
- `src/dom.js`: required/optional DOM helpers.
- `src/types.js`: JSDoc payload contracts.
- `styles`: base tokens, layout, components, and graph-specific CSS.
- `tests`: Vitest/jsdom frontend tests.

## `examples/`

Small scripts showing public API and integration usage. These are useful as
smoke examples and as starting points for user integrations.

## `tests/`

Backend contract, storage, API, migration, public-client, slug, delete, and
agent-tooling tests.
